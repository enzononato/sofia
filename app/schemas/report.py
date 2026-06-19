"""Schemas for the reports/analytics endpoints."""

from pydantic import BaseModel


class TrendPoint(BaseModel):
    date: str  # YYYY-MM-DD
    count: int


class NamedCount(BaseModel):
    label: str
    count: int


class MessageVolumePoint(BaseModel):
    date: str
    inbound: int
    outbound: int


class ReportOverview(BaseModel):
    days: int
    total_contacts: int
    new_contacts: int            # within the window
    converted_contacts: int      # crm_stage in scheduled/attended/post_care
    conversion_rate: float       # converted / total (0..1)
    total_appointments: int      # within the window
    upcoming_appointments: int
    no_show_rate: float          # no_show / (completed + no_show), 0..1
    leads_trend: list[TrendPoint]
    stage_distribution: list[NamedCount]
    appointments_by_status: list[NamedCount]
    top_services: list[NamedCount]
    messages_volume: list[MessageVolumePoint]
