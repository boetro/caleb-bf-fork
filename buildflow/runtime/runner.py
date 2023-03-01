import argparse
import dataclasses
import logging
import json
import os
import requests
import sys
import tempfile
import traceback
from typing import Dict, Iterable, Optional
import uuid

import ray
from buildflow.api import ProcessorAPI, resources
from buildflow.runtime.ray_io import (bigquery_io, duckdb_io, empty_io,
                                      pubsub_io, redis_stream_io)

# TODO: Add support for other IO types.
_IO_TYPE_TO_SOURCE = {
    resources.BigQuery.__name__: bigquery_io.BigQuerySourceActor,
    resources.DuckDB.__name__: duckdb_io.DuckDBSourceActor,
    resources.Empty.__name__: empty_io.EmptySourceActor,
    resources.PubSub.__name__: pubsub_io.PubSubSourceActor,
    resources.RedisStream.__name__: redis_stream_io.RedisStreamInput,
}

# TODO: Add support for other IO types.
_IO_TYPE_TO_SINK = {
    resources.BigQuery.__name__: bigquery_io.BigQuerySinkActor,
    resources.DuckDB.__name__: duckdb_io.DuckDBSinkActor,
    resources.Empty.__name__: empty_io.EmptySinkActor,
    resources.PubSub.__name__: pubsub_io.PubsubSinkActor,
    resources.RedisStream.__name__: redis_stream_io.RedisStreamOutput,
}


@dataclasses.dataclass
class _ProcessorRef:
    processor_class: type
    input_ref: type
    output_ref: type


_SESSION_DIR = os.path.join(tempfile.gettempdir(), 'buildflow')
_SESSION_FILE = os.path.join(_SESSION_DIR, 'build_flow_usage.json')


@ray.remote
class _ProcessActor(object):

    def __init__(self, processor_class):
        self._processor: ProcessorAPI = processor_class()
        print(f'Running processor setup: {self._processor.__class__}')
        self._processor._setup()

    # TODO: Add support for process_async
    def process(self, *args, **kwargs):
        return self._processor.process(*args, **kwargs)

    def process_batch(self, calls: Iterable):
        to_ret = []
        for call in calls:
            to_ret.append(self.process(call))
        return to_ret


def _load_session_id():
    try:
        os.makedirs(_SESSION_DIR, exist_ok=True)
        if os.path.exists(_SESSION_FILE):
            with open(_SESSION_FILE, 'r') as f:
                session_info = json.load(f)
                return session_info['id']
        else:
            session_id = str(uuid.uuid4())
            with open(_SESSION_FILE, 'w') as f:
                json.dump({'id': session_id}, f)
            return session_id
    except Exception as e:
        logging.debug('failed to load session id with error: %s', e)


class Runtime:
    # NOTE: This is the singleton class.
    _instance = None
    _initialized = False
    _session_id = None
    _enable_usage = True

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._processors: Dict[str, _ProcessorRef] = {}
        self._session_id = _load_session_id()
        parser = argparse.ArgumentParser()
        parser.add_argument('--disable_usage_stats',
                            action='store_false',
                            default=False)
        args, _ = parser.parse_known_args(sys.argv)
        if args.disable_usage_stats:
            self._enable_usage = False

    # This method is used to make this class a singleton
    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super().__new__(cls)
        return cls._instance

    def run(self, num_replicas: int):
        if self._enable_usage:
            print(
                'Usage stats collection is enabled. To disable add the flag: '
                '`--disable_usage_stats`.')
            response = requests.post(
                'https://apis.launchflow.com/buildflow_usage',
                data=json.dumps({'id': self._session_id}))
            if response.status_code == 200:
                logging.debug('recorded run in session %s', self._session_id)
            else:
                logging.debug('failed to record usage stats.')
        print('Starting Flow Runtime')

        try:
            output = self._run(num_replicas)
            print('Flow finished successfully')
            return output
        except Exception as e:
            print('Flow failed with error: ', e)
            traceback.print_exc()
            raise e
        finally:
            # Reset the processors after each run. This may cause issues if
            # folks call run multiple times within a run. But it feels a more
            # straight forward.
            self._reset()

    def _reset(self):
        # TODO: Add support for multiple node types (i.e. endpoints).
        self._processors = {}

    def _run(self, num_replicas: int):
        # TODO: Support multiple processors
        processor_ref = list(self._processors.values())[0]

        # TODO: Add comments to explain this code, its pretty dense with
        # need-to-know info.
        source_actor_class = _IO_TYPE_TO_SOURCE[
            processor_ref.input_ref.__class__.__name__]
        sink_actor_class = _IO_TYPE_TO_SINK[
            processor_ref.output_ref.__class__.__name__]
        source_args = source_actor_class.source_args(processor_ref.input_ref,
                                                     num_replicas)
        source_pool_tasks = []
        for args in source_args:
            processor_actor = _ProcessActor.remote(
                processor_ref.processor_class)
            sink = sink_actor_class.remote(
                processor_actor.process_batch.remote, processor_ref.output_ref)
            # TODO: probably need support for unique keys. What if someone
            # writes to two bigquery tables?
            source = source_actor_class.remote(
                {str(processor_ref.output_ref): sink}, *args)
            num_threads = source_actor_class.recommended_num_threads()
            source_pool_tasks.extend(
                [source.run.remote() for _ in range(num_threads)])

        # We no longer need to use the Actor Pool because there's no input to
        # the actors (they spawn their own inputs based on the IO refs).
        # We also need to await each actor's subtask separately because its
        # now running on multiple threads.
        all_actor_outputs = ray.get(source_pool_tasks)

        # TODO: Add option to turn this off for prod deployments
        # Otherwise I think we lose time to sending extra data over the wire.
        final_output = {}
        for actor_output in all_actor_outputs:
            if actor_output is not None:
                for key, value in actor_output.items():
                    if key in final_output:
                        final_output[key].extend(value)
                    else:
                        final_output[key] = value
        return final_output

    def register_processor(self,
                           processor_class: type,
                           input_ref: resources.IO,
                           output_ref: resources.IO,
                           processor_id: Optional[str] = None):
        if processor_id is None:
            processor_id = processor_class.__qualname__
        if processor_id in self._processors:
            logging.warning(
                f'Processor {processor_id} already registered. Overwriting.')
        # TODO: Support multiple processors
        elif len(self._processors) > 0:
            raise RuntimeError(
                'The Runner API currently only supports a single processor.')

        self._processors[processor_id] = _ProcessorRef(processor_class,
                                                       input_ref, output_ref)
