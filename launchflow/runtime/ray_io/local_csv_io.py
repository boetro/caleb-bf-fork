"""IO connectors for DuckDB and Ray."""

import logging
import os
import time
from typing import Any, Callable, Dict, Iterable, Union

import duckdb
import pandas as pd
import ray

from launchflow.api import resources
from launchflow.runtime.ray_io import base


@ray.remote
class LocalCSVSourceActor(base.RaySource):

    def __init__(
        self,
        ray_sinks: Iterable[base.RaySink],
        local_sv_ref=resources.LocalCSV,
    ) -> None:
        super().__init__(ray_sinks)
        self.duck_con = duckdb.connect(database=duckdb_ref.database,
                                       read_only=True)
        query = duckdb_ref.query
        if not query:
            query = f'SELECT * FROM {duckdb_ref.table}'
        self.duck_con.execute(query=query)

    @classmethod
    def source_inputs(cls, io_ref: resources.LocalCSV, num_replicas: int):
        csv_path = io_ref.file_path
        if io_ref.query:
            # TODO: use DuckDB to issue a query on it.
            pass
        size = os.path.getsize(csv_path)
        return super().source_inputs(io_ref, num_replicas)

    def run(self):
        refs = []
        df = self.duck_con.fetch_df_chunk()
        while not df.empty:
            elements = df.to_dict('records')
            for ray_sink in self.ray_sinks:
                for element in elements:
                    refs.append(ray_sink.write.remote(element))
            df = self.duck_con.fetch_df_chunk()
        self.duck_con.close()
        return ray.get(refs)


_MAX_CONNECT_TRIES = 20


@ray.remote
class DuckDBSinkActor(base.RaySink):

    def __init__(
        self,
        remote_fn: Callable,
        duckdb_ref: resources.DuckDB,
    ) -> None:
        super().__init__(remote_fn)
        self.database = duckdb_ref.database
        self.table = duckdb_ref.table

    def _write(
        self,
        element: Union[Dict[str, Any], Iterable[Dict[str, Any]]],
    ):

        connect_tries = 0
        while connect_tries < _MAX_CONNECT_TRIES:
            try:
                duck_con = duckdb.connect(database=self.database,
                                          read_only=False)
                break
            except duckdb.IOException as e:
                if 'Could not set lock on file' in str(e):
                    connect_tries += 1
                    if connect_tries == _MAX_CONNECT_TRIES:
                        raise ValueError(
                            'Failed to connect to duckdb. Did you leave a '
                            'connection open?') from e
                    logging.warning(
                        'Can\'t concurrently write to DuckDB waiting 2 '
                        'seconds then will try again.')
                    time.sleep(2)
                else:
                    raise e
        if isinstance(element, dict):
            df = pd.DataFrame([element])
        else:
            df = pd.DataFrame(element)
        try:
            duck_con.append(self.table, df)
        except duckdb.CatalogException:
            # This can happen if the table doesn't exist yet. If this
            # happen create it from the DF.
            duck_con.execute(f'CREATE TABLE {self.table} AS SELECT * FROM df')
        duck_con.close()
        return
