from __future__ import annotations

from src.domain import unified_jd_structured_spans_v4 as v4
from src.domain import unified_jd_structured_spans_v7 as v7


def _span(source: str, start: int, end: int) -> v4.SourceSpan:
    return v4.SourceSpan.from_bounds(source, start, end)


def _member(source: str, member_id: str, start: int, end: int) -> v4.CoordinationMember:
    return v4.CoordinationMember(member_id, _span(source, start, end), 0)


def _parsed(
    source: str,
    *,
    wrappers: tuple[v4.WrapperSpan, ...] = (),
    labels: tuple[v4.ConnectorLabel, ...] = (),
    groups: tuple[v4.CoordinationGroup, ...] = (),
    scopes: tuple[v4.SharedScope, ...] = (),
    attachments: tuple[v4.ExampleAttachment, ...] = (),
    candidates: tuple[v4.CoordinationMember, ...] = (),
    protected: tuple[v4.SourceSpan, ...] = (),
) -> v4.ParsedClause:
    return v4.ParsedClause(
        source_text=source,
        category="skill",
        protected_spans=protected,
        segments=(_span(source, 0, len(source)),),
        wrappers=wrappers,
        connector_labels=labels,
        coordinations=groups,
        shared_scopes=scopes,
        example_attachments=attachments,
        item_candidates=candidates,
        rule_ids=("synthetic",),
    )


def _implicit_enumeration_graphs(
    source: str = "A、B等模块", *, protected: bool = False
) -> tuple[v4.ParsedClause, v4.ParsedClause]:
    a = _member(source, "base-a", source.index("A"), source.index("A") + 1)
    b = _member(source, "base-b", source.index("B"), source.index("B") + 1)
    cue_start = source.index("等")
    parent_start = cue_start + 1
    base = _parsed(source, candidates=(a, b))
    example_a = _member(source, "example-a", a.span.start, a.span.end)
    example_b = _member(source, "example-b", b.span.start, b.span.end)
    connector = _span(source, source.index("、"), source.index("、") + 1)
    attachment = v4.ExampleAttachment(
        "attachment-1",
        _span(source, cue_start, cue_start + 1),
        _span(source, parent_start, len(source)),
        (example_a.span, example_b.span),
        0,
    )
    baseline = _parsed(
        source,
        labels=(v4.ConnectorLabel(connector, "example"),),
        groups=(
            v4.CoordinationGroup(
                "group-1", "example", "synthetic", (connector,), (example_a, example_b)
            ),
        ),
        attachments=(attachment,),
        candidates=(_member(source, "parent", parent_start, len(source)),),
        protected=(_span(source, 0, len(source)),) if protected else (),
    )
    return base, baseline


def test_s1_fires_for_complete_implicit_partition() -> None:
    source = "A、B等模块"
    base, baseline = _implicit_enumeration_graphs(source)

    result = v7._s1_conflict(source, base, baseline)

    assert result.outcome == "fired"
    assert result.envelope is not None


def test_s1_vetoes_explicit_and_protected_attachments() -> None:
    explicit = "如A、B等模块"
    base, baseline = _implicit_enumeration_graphs(explicit)
    protected_source = "A、B等模块"
    protected_base, protected_baseline = _implicit_enumeration_graphs(
        protected_source, protected=True
    )

    assert v7._s1_conflict(explicit, base, baseline).outcome == "veto:explicit-cue"
    assert (
        v7._s1_conflict(protected_source, protected_base, protected_baseline).outcome
        == "veto:protected-attachment"
    )


def test_s1_vetoes_incomplete_partition_and_preserved_atoms() -> None:
    source = "A、B等模块"
    base, baseline = _implicit_enumeration_graphs(source)
    incomplete = _parsed(source, candidates=(base.item_candidates[0],))
    preserved = _parsed(
        source,
        labels=baseline.connector_labels,
        groups=baseline.coordinations,
        attachments=baseline.example_attachments,
        candidates=(*base.item_candidates, *baseline.item_candidates),
    )

    assert v7._s1_conflict(source, incomplete, baseline).outcome.startswith("veto:")
    assert (
        v7._s1_conflict(source, base, preserved).outcome
        == "veto:additive-or-preserved"
    )


def test_s2_fires_for_wrapper_contamination() -> None:
    source = "preA"
    atom = _member(source, "atom", 3, 4)
    base = _parsed(source, candidates=(atom,))
    baseline = _parsed(
        source,
        wrappers=(v4.WrapperSpan("prefix", _span(source, 0, 3), atom.span),),
        candidates=(_member(source, "broad", 0, 4),),
    )

    assert v7._s2_conflict(source, base, baseline).outcome == "fired"


def test_s2_vetoes_preserved_atoms_and_explicit_attachment() -> None:
    source = "preA"
    atom = _member(source, "atom", 3, 4)
    base = _parsed(source, candidates=(atom,))
    preserved = _parsed(source, candidates=(_member(source, "same", 3, 4),))
    explicit_source = "如A"
    explicit_atom = _member(explicit_source, "explicit-atom", 1, 2)
    explicit_attachment = v4.ExampleAttachment(
        "attachment",
        _span(explicit_source, 0, 1),
        explicit_atom.span,
        (explicit_atom.span,),
        0,
    )
    explained = _parsed(
        explicit_source,
        attachments=(explicit_attachment,),
        candidates=(_member(explicit_source, "broad", 0, 2),),
    )

    assert v7._s2_conflict(source, base, preserved).outcome.startswith("veto:")
    assert (
        v7._s2_conflict(
            explicit_source,
            _parsed(explicit_source, candidates=(explicit_atom,)),
            explained,
        ).outcome
        == "veto:explicit-attachment"
    )


def _s3_graphs(
    *, include_residual: bool = True, close_scope: bool = True
) -> tuple[str, v4.ParsedClause, v4.ParsedClause]:
    source = "A等P或Q有R"
    example = _span(source, 0, 1)
    cue = _span(source, 1, 2)
    p = _member(source, "p", 2, 3)
    connector = _span(source, 3, 4)
    q = _member(source, "q", 4, 5)
    operator = _span(source, 5, 7)
    base_scope_member = p if close_scope else _member(source, "other", 0, 1)
    base = _parsed(
        source,
        groups=(
            v4.CoordinationGroup(
                "base-group", "surface", "synthetic", (connector,), (p, q)
            ),
        ),
        scopes=(
            v4.SharedScope(
                "base-scope", "evidence", operator, (base_scope_member.id,)
            ),
        ),
        attachments=(
            v4.ExampleAttachment("base-attachment", cue, p.span, (example,), 0),
        ),
        candidates=(
            *((base_scope_member,) if not close_scope else ()),
            _member(source, "base-p", 2, 3),
            _member(source, "base-q", 4, 5),
            _member(source, "base-r", 6, 7),
        ),
    )
    candidates = [
        _member(source, "current-p", 2, 3),
        _member(source, "current-q", 4, 5),
    ]
    if include_residual:
        candidates.append(_member(source, "residual", 5, 7))
    baseline = _parsed(
        source,
        groups=(
            v4.CoordinationGroup(
                "current-group", "surface", "synthetic", (connector,), (p, q)
            ),
        ),
        labels=(v4.ConnectorLabel(connector, "surface"),),
        attachments=(
            v4.ExampleAttachment(
                "current-attachment", cue, _span(source, 2, 5), (example,), 0
            ),
        ),
        candidates=tuple(candidates),
    )
    return source, base, baseline


def test_s3_fires_for_closed_cross_coordination_bundle() -> None:
    source, base, baseline = _s3_graphs()

    assert v7._s3_conflict(source, base, baseline).outcome == "fired"


def test_s3_vetoes_parent_width_residual_and_reference_failures() -> None:
    source, base, no_residual = _s3_graphs(include_residual=False)
    _, open_base, baseline = _s3_graphs(close_scope=False)
    same_parent = _parsed(
        source,
        groups=baseline.coordinations,
        labels=baseline.connector_labels,
        attachments=baseline.example_attachments,
        candidates=baseline.item_candidates,
    )

    assert v7._s3_conflict(source, base, no_residual).outcome == "veto:no-residual-operator"
    assert v7._s3_conflict(source, open_base, baseline).outcome == "veto:reference-closure"
    assert v7._s3_conflict(source, same_parent, baseline).outcome.startswith("veto:")


def test_supported_v5_restoration_requires_complete_envelope_coverage() -> None:
    source = "doA"
    narrow = _member(source, "narrow", 2, 3)
    broad = _member(source, "broad", 0, 3)
    fresh = _parsed(
        source,
        wrappers=(v4.WrapperSpan("prefix", _span(source, 0, 2), narrow.span),),
        candidates=(narrow,),
    )
    baseline = _parsed(source, candidates=(broad,))
    envelopes = v7._supported_envelopes(source, fresh, baseline)

    licensed, mechanism, _ = v7._licensed_family(
        fresh, baseline, "item_candidates", envelopes
    )

    assert licensed
    assert "E2-wrapper-boundary" in mechanism
    assert not v7._licensed_family(
        _parsed(source, candidates=(narrow,)), baseline, "item_candidates", ()
    )[0]


def test_conflict_precedence_vetoes_supported_restoration() -> None:
    source = "preA"
    atom = _member(source, "atom", 3, 4)
    base = _parsed(
        source,
        wrappers=(v4.WrapperSpan("prefix", _span(source, 0, 3), atom.span),),
        candidates=(atom,),
    )
    fresh = _parsed(
        source,
        wrappers=(v4.WrapperSpan("prefix", _span(source, 0, 3), atom.span),),
        candidates=(atom,),
    )
    baseline = _parsed(source, candidates=(_member(source, "broad", 0, 4),))

    plan = v7._selection_plan(source, base, fresh, baseline)

    assert plan.origins["item_candidates"] == "v4"
    assert any("supported-v5" in value and "veto:runtime-conflict" in value for value in plan.trace)


def test_rebuild_rebases_scope_ids_and_projects_from_graph_once() -> None:
    source = "A或B"
    connector = _span(source, 1, 2)
    a = _member(source, "a", 0, 1)
    b = _member(source, "b", 2, 3)
    parsed = _parsed(
        source,
        labels=(v4.ConnectorLabel(connector, "surface"),),
        groups=(
            v4.CoordinationGroup(
                "group", "surface", "synthetic", (connector,), (a, b)
            ),
        ),
        scopes=(v4.SharedScope("scope", "suffix", b.span, (a.id, b.id)),),
        candidates=(
            _member(source, "candidate-a", 0, 1),
            _member(source, "candidate-b", 2, 3),
        ),
    )
    parses = {"v4": parsed, "v5": parsed, "v6": parsed}
    plan = v7._SelectionPlan({family: "v6" for family in v7._FAMILIES}, ())

    rebuilt = v7._rebuild(source, "skill", parses, plan)
    extraction = v7.project_surface_items(rebuilt)
    known = {
        member.id for group in rebuilt.coordinations for member in group.members
    } | {candidate.id for candidate in rebuilt.item_candidates}

    assert all(set(scope.applies_to_member_ids) <= known for scope in rebuilt.shared_scopes)
    assert extraction.items == ("A", "B")
