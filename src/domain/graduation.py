"""Conservative classification of cohort evidence, independent of model labels."""

import re
from typing import Literal

GraduationConditionKind = Literal["simple", "qualified", "ambiguous"]


def classify_graduation_condition(source_text: str) -> GraduationConditionKind:
    text = re.sub(r"\s+", "", source_text).strip("。.;；")
    # Only an explicit list of cohorts is safe for a year-membership check.
    year = r"20\d{2}(?:年)?(?:届)?"
    if re.fullmatch(
        rf"(?:面向|招收|招聘|接受|限)?{year}(?:(?:、|，|,|和|或|及|/){year})*"
        r"(?:应届)?(?:毕业生|毕业学生|应届生)?",
        text,
    ):
        return "simple"
    if re.search(
        r"国内|大陆|境内|海外|境外|留学|毕业时间|毕业日期|取得|获得|之前|之后|至|到|[月日]|仅|限|且|如果",
        text,
    ):
        return "qualified"
    return "ambiguous"
