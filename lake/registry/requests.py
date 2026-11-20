from lake.registry.catalog import Catalog
from lake.registry.identity import VolumeId, validate_job_id
from lake.registry.ledger import JobBinding as JobBinding
from lake.registry.ledger import RegistryLedger
from lake.registry.policy import DEFAULT_POLICY


class RequestRegistry:
    def __init__(self, catalog: Catalog, ledger: RegistryLedger):
        self.catalog = catalog
        self.ledger = ledger

    def start(self, job_id: str, first: VolumeId, second: VolumeId) -> JobBinding:
        job_id = validate_job_id(job_id)
        self.catalog.get_volume(first)
        self.catalog.get_volume(second)
        if first == second:
            raise ValueError('a merge requires two distinct volumes')
        volumes = (first, second)
        binding = self.ledger.put_job_if_absent(JobBinding(job_id, volumes, DEFAULT_POLICY))
        if binding.volumes != volumes:
            raise ValueError(f'job {job_id!r} already binds a different ordered pair')
        return binding

    def get_binding(self, job_id: str) -> JobBinding:
        job_id = validate_job_id(job_id)
        binding = self.ledger.get_job(job_id)
        if binding is None:
            raise KeyError(job_id)
        return binding
