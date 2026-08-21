from __future__ import annotations

from deopjufier.opju.reports import parse_opju_origin_storage_reports


def test_tolerant_analysis_report_parsing_is_explicit() -> None:
    payload = (
        b'<OriginStorage OperationIndividualVersionNum="StatsOpBase\tFitterOperation;2\t3">'
        b"<NLFitXFName>FitLinear</NLFitXFName>"
        b'<Calculation AnalysisName="FitLinear" Label="Linear Fit">'
        b"<Equation>y = a + b*x</Equation>"
        b"<UserName>analyst</UserName>"
        b"<Time>2026-01-02 03:04:05</Time>"
        b'<X EscTransl="[Book1]Sheet1!A">x</X>'
        b"<Broken>\x7f</Calculation></OriginStorage>"
    )
    data = b"CPYUA 4.3318 0\x00" + payload

    assert parse_opju_origin_storage_reports(data) == []

    reports = parse_opju_origin_storage_reports(data, include_analyses=True)

    assert len(reports) == 1
    report = reports[0]
    assert report.label == "Linear Fit"
    assert report.function == "FitLinear"
    assert report.equation == "y = a + b*x"
    assert report.user == "analyst"
    assert report.time == "2026-01-02 03:04:05"
    assert report.input_data == ["[Book1]Sheet1!A"]
    equation_field = next(field for field in report.fields if field.tag == "Equation")
    equation_start = data.index(b"y = a + b*x")
    assert equation_field.value == "y = a + b*x"
    assert equation_field.source_start == equation_start
    assert equation_field.source_end == equation_start + len(b"y = a + b*x")
    assert equation_field.path == "OriginStorage/Calculation/Equation"
    assert equation_field.to_dict()["verification"] == "exact"
    assert all(field.tag != "Broken" for field in report.fields)
