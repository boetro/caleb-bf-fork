from typing import Any, Callable, Dict, List, Optional, Type

from buildflow.core.io.utils.clients import gcp_clients
from buildflow.core.io.utils.schemas import converters
from buildflow.core.strategies.sink import SinkStrategy
from buildflow.core.types.gcp_types import (
    BigQueryDatasetName,
    GCPProjectID,
    BigQueryTableID,
    BigQueryTableName,
)


class StreamingBigQueryTableSink(SinkStrategy):
    def __init__(
        self,
        *,
        project_id: GCPProjectID,
        dataset_name: BigQueryDatasetName,
        table_name: BigQueryTableName,
        batch_size: int = 10_000,
    ):
        super().__init__(strategy_id="streaming-bigquery-table-sink")
        # configuration
        self.project_id = project_id
        self.dataset_name = dataset_name
        self.table_name = table_name
        self.batch_size = batch_size
        # setup
        self.bq_client = gcp_clients.get_bigquery_client(self.project_id)

    @property
    def table_id(self) -> BigQueryTableID:
        return f"{self.project_id}.{self.dataset_name}.{self.table_name}"

    async def push(self, batch: List[dict]):
        for i in range(0, len(batch), self.batch_size):
            rows = batch[i : i + self.batch_size]
            errors = self.bq_client.insert_rows_json(self.table_id, rows)
            if errors:
                raise RuntimeError(f"BigQuery streaming insert failed: {errors}")

    def push_converter(
        self, user_defined_type: Optional[Type]
    ) -> Callable[[Any], Dict[str, Any]]:
        return converters.json_push_converter(user_defined_type)
