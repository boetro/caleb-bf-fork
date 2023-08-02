from typing import Optional, Type

from buildflow.core.credentials import EmptyCredentials
from buildflow.core.io.local.strategies.duckdb_strategies import DuckDBSink
from buildflow.core.providers.provider import PulumiProvider, SinkProvider
from buildflow.core.types.local_types import DuckDBDatabase, DuckDBTable


class DuckDBProvider(SinkProvider, PulumiProvider):
    def __init__(
        self,
        *,
        database: DuckDBDatabase,
        table: DuckDBTable,
        # source-only options
        # sink-only options
        # pulumi-only options
    ):
        self.database = database
        self.table = table
        # sink-only options
        # pulumi-only options

    def sink(self, credentials: EmptyCredentials):
        return DuckDBSink(
            credentials=credentials,
            database=self.database,
            table=self.table,
        )

    def pulumi_resources(
        self,
        type_: Optional[Type],
        credeitnals: EmptyCredentials,
        depends_on: list = [],
    ):
        # Local file provider does not have any Pulumi resources
        return []
