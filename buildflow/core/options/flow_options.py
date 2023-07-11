import dataclasses

from buildflow.core.options._options import Options
from buildflow.core.options.infra_options import InfraOptions
from buildflow.core.options.runtime_options import RuntimeOptions


@dataclasses.dataclass
class FlowOptions(Options):
    runtime_options: RuntimeOptions
    infra_options: InfraOptions

    @classmethod
    def default(cls) -> "FlowOptions":
        return cls(
            runtime_options=RuntimeOptions.default(),
            infra_options=InfraOptions.default(),
        )
