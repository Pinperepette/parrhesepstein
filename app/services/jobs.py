"""
JobManager unificato — sostituisce i 13+ dict separati di app.py.
"""


class JobManager:
    """Store in-memory per tutti i job in background."""

    def __init__(self):
        self._store = {}  # {job_type: {job_id: dict}}

    def create_job(self, job_type, job_id, initial_data=None):
        bucket = self._store.setdefault(job_type, {})
        job = {
            "status": "pending",
            "progress": "In coda...",
            "result": None,
            "error": None,
        }
        if initial_data:
            job.update(initial_data)
        bucket[job_id] = job
        return job_id

    def get_job(self, job_type, job_id):
        return self._store.get(job_type, {}).get(job_id)

    def update_job(self, job_type, job_id, **kwargs):
        job = self.get_job(job_type, job_id)
        if job:
            job.update(kwargs)


job_manager = JobManager()
