from typing import Literal

from pydantic import BaseModel, ConfigDict


class AccountExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmed: Literal[True]


class AccountDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmation: Literal["DELETE_MY_DATA"]


class AccountDataSummaryRead(BaseModel):
    record_counts: dict[str, int]
    related_application_count: int
    related_job_posting_count: int
    resume_file_count: int
    resume_file_bytes: int


class AccountDeletionRead(BaseModel):
    deleted_counts: dict[str, int]
    deleted_application_count: int
    deleted_exclusive_job_count: int
    deleted_resume_file_count: int
