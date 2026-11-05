"""loyalty tasks — placeholder replaced by the owning workstream."""

from app.celery_app import celery


@celery.task(name="app.tasks.loyalty.calculate_monthly_multipliers")
def calculate_monthly_multipliers() -> str:
    raise NotImplementedError("calculate_monthly_multipliers is implemented by its workstream")
