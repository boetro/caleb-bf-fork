import inspect
from typing import Any, Callable, Optional, TypeVar


class Source:
    """Super class for all source types."""

    def setup(self):
        """Perform any setup that is needed to connect to a source."""

    def actor(self, ray_sinks):
        """Returns the actor associated with the source."""
        pass

    def preprocess(self, element: Any) -> Any:
        return element

    @classmethod
    def recommended_num_threads(cls):
        # Each class that implements RaySource can use this to suggest a good
        # number of threads to use when creating the source in the runtime.
        return 1

    @classmethod
    def is_streaming(cls) -> bool:
        return False


class StreamingSource(Source):

    def backlog(self) -> Optional[int]:
        """Returns an estimate of the backlog for the source.

        This method will be polled by our manager to determine if we need to
        scale up the number of actor replicas.
        """
        raise NotImplementedError(
            'backlog should be implemented for streaming sources.')

    @classmethod
    def is_streaming(cls) -> bool:
        return True


SourceType = TypeVar('SourceType', bound=Source)


class Sink:
    """Super class for all sink types."""

    def setup(self, process_arg_spec: inspect.FullArgSpec):
        """Perform any setup that is needed to connect to a sink.

        Args:
            process_arg_spec: The arg spec for the process function defined by
                the user.
        """

    def actor(self, remote_fn: Callable, is_streaming: bool):
        """Returns the actor associated with the sink."""
        pass


SinkType = TypeVar('SinkType', bound=Sink)
