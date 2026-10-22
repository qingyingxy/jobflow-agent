from __future__ import annotations

from src.domain import unified_jd_structured_spans_v4 as v4
from src.domain import unified_jd_structured_spans_v8 as v8


def _span(source: str, start: int, end: int) -> v4.SourceSpan:
    return v4.SourceSpan.from_bounds(source, start, end)


def _member(source: str, member_id: str, start: int, end: int) -> v4.CoordinationMember:
    return v4.CoordinationMember(member_id, _span(source, start, end), 0)


def _parsed(
    source: str,
    *,
    segments: tuple[v4.SourceSpan, ...] | None = None,
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
        segments=segments or (_span(source, 0, len(source)),),
        wrappers=wrappers,
        connector_labels=labels,
        coordinations=groups,
        shared_scopes=scopes,
        example_attachments=attachments,
        item_candidates=candidates,
        rule_ids=("synthetic",),
    )


def _graph(
    source: str,
    v4_graph: v4.ParsedClause,
    v5_graph: v4.ParsedClause,
    v6_graph: v4.ParsedClause,
) -> tuple[tuple[v8._DeltaNode, ...], tuple[v8._Component, ...]]:
    nodes = v8._delta_nodes({"v4": v4_graph, "v5": v5_graph, "v6": v6_graph})
    return nodes, v8._components(source, nodes)


def _first_component(
    source: str, fresh: v4.ParsedClause, baseline: v4.ParsedClause
) -> tuple[tuple[v8._DeltaNode, ...], v8._Component]:
    nodes, components = _graph(source, baseline, fresh, baseline)
    assert components
    return nodes, components[0]


def _witness(mechanism: str, source: str, component: v8._Component) -> v8._Witness:
    return v8._Witness(
        mechanism,
        _span(source, component.envelope.start, component.envelope.end),
        frozenset({component.id}),
    )


def test_e2_activation_requires_wrapper_and_structural_dependent() -> None:
    source = "doA"
    atom = _member(source, "atom", 2, 3)
    fresh = _parsed(
        source,
        wrappers=(v4.WrapperSpan("prefix", _span(source, 0, 2), atom.span),),
        candidates=(atom,),
    )
    baseline = _parsed(source, candidates=(_member(source, "broad", 0, 3),))
    nodes, components = _graph(source, baseline, fresh, baseline)

    witnesses = v8._e2_witnesses(source, fresh, baseline, nodes, components)

    assert len(witnesses) == 1
    assert witnesses[0].component_ids


def test_e3_activation_requires_role_and_topology_delta() -> None:
    source = "A、B等P"
    connector = _span(source, 1, 2)
    a = _member(source, "a", 0, 1)
    b = _member(source, "b", 2, 3)
    cue = _span(source, 3, 4)
    parent = _span(source, 4, 5)
    fresh = _parsed(
        source,
        labels=(v4.ConnectorLabel(connector, "example"),),
        groups=(
            v4.CoordinationGroup(
                "examples", "example", "synthetic", (connector,), (a, b)
            ),
        ),
        attachments=(
            v4.ExampleAttachment("attachment", cue, parent, (a.span, b.span), 0),
        ),
        candidates=(_member(source, "parent", 4, 5),),
    )
    baseline = _parsed(
        source,
        labels=(v4.ConnectorLabel(connector, "surface"),),
        groups=(
            v4.CoordinationGroup(
                "surface", "surface", "synthetic", (connector,), (a, b)
            ),
        ),
        candidates=(
            _member(source, "candidate-a", 0, 1),
            _member(source, "candidate-b", 2, 3),
        ),
    )
    nodes, components = _graph(source, baseline, fresh, baseline)

    witnesses = v8._e3_witnesses(source, fresh, baseline, nodes, components)

    assert len(witnesses) == 1
    assert witnesses[0].component_ids


def test_e6_uses_typed_wrapper_spans_in_envelope() -> None:
    source = "以下经验：A/B等优先"
    header = _span(source, 0, source.index("："))
    body = _span(source, source.index("A"), len(source))
    examples = _span(source, source.index("A"), source.index("等"))
    cue = _span(source, source.index("等"), source.index("等") + 1)
    priority = _span(source, source.index("优"), len(source))
    fresh = _parsed(
        source,
        segments=(header, body),
        wrappers=(
            v4.WrapperSpan("open_list_suffix", cue, examples),
            v4.WrapperSpan(
                "suffix", priority, _span(source, body.start, priority.start)
            ),
        ),
    )

    witnesses = v8._e6_witnesses(source, fresh, (), ())

    assert len(witnesses) == 1
    assert witnesses[0].envelope.text == source


def test_e7_activation_keeps_prepositional_example_signature() -> None:
    source = "对A、B等领域"
    a = _span(source, 1, 2)
    b = _span(source, 3, 4)
    fresh = _parsed(
        source,
        wrappers=(v4.WrapperSpan("prefix", _span(source, 0, 1), _span(source, 1, 4)),),
        attachments=(
            v4.ExampleAttachment(
                "attachment",
                _span(source, 4, 5),
                _span(source, 5, 7),
                (a, b),
                0,
            ),
        ),
    )

    witnesses = v8._e7_witnesses(source, fresh, (), ())

    assert len(witnesses) == 1
    assert witnesses[0].mechanism.startswith("E7")


def test_compatibility_vetoes_complete_surface_partition_deletion() -> None:
    source = "A、B"
    connector = _span(source, 1, 2)
    a = _member(source, "member-a", 0, 1)
    b = _member(source, "member-b", 2, 3)
    baseline = _parsed(
        source,
        groups=(
            v4.CoordinationGroup(
                "surface", "surface", "synthetic", (connector,), (a, b)
            ),
        ),
        candidates=(
            _member(source, "candidate-a", 0, 1),
            _member(source, "candidate-b", 2, 3),
        ),
    )
    fresh = _parsed(source)
    nodes, component = _first_component(source, fresh, baseline)
    witness = _witness("E6-priority-tail-rejection", source, component)

    assert (
        v8._compatibility(component, (witness,), (witness,), nodes, fresh, baseline)
        == "veto:surface-partition-deletion"
    )


def test_compatibility_vetoes_unsupported_surface_to_example_transfer() -> None:
    source = "A、B等P"
    a = _member(source, "a", 0, 1)
    b = _member(source, "b", 2, 3)
    baseline = _parsed(source, candidates=(a, b))
    fresh = _parsed(
        source,
        attachments=(
            v4.ExampleAttachment(
                "attachment",
                _span(source, 3, 4),
                _span(source, 4, 5),
                (a.span, b.span),
                0,
            ),
        ),
        candidates=(_member(source, "parent", 4, 5),),
    )
    nodes, component = _first_component(source, fresh, baseline)
    witness = _witness("E3-region-first-connector-role", source, component)

    assert (
        v8._compatibility(component, (witness,), (witness,), nodes, fresh, baseline)
        == "veto:unsupported-role-transfer"
    )


def test_compatibility_vetoes_attachment_loss() -> None:
    source = "如A为P"
    attachment = v4.ExampleAttachment(
        "attachment",
        _span(source, 0, 1),
        _span(source, 3, 4),
        (_span(source, 1, 2),),
        0,
    )
    baseline = _parsed(source, attachments=(attachment,))
    fresh = _parsed(source)
    nodes, component = _first_component(source, fresh, baseline)
    witness = _witness("E3-region-first-connector-role", source, component)

    assert (
        v8._compatibility(component, (witness,), (witness,), nodes, fresh, baseline)
        == "veto:attachment-loss"
    )


def test_compatibility_vetoes_protected_attachment_broadening() -> None:
    source = "(A)PQ"
    cue = _span(source, 0, 1)
    example = _span(source, 1, 2)
    prior = v4.ExampleAttachment("prior", cue, _span(source, 3, 4), (example,), 0)
    current = v4.ExampleAttachment("current", cue, _span(source, 3, 5), (example,), 0)
    protected = (_span(source, 0, 3),)
    baseline = _parsed(source, attachments=(prior,), protected=protected)
    fresh = _parsed(source, attachments=(current,), protected=protected)
    nodes, component = _first_component(source, fresh, baseline)
    witness = _witness("E3-region-first-connector-role", source, component)

    assert (
        v8._compatibility(component, (witness,), (witness,), nodes, fresh, baseline)
        == "veto:protected-attachment-reparent"
    )


def test_compatibility_vetoes_atomic_producer_contamination() -> None:
    source = "doA"
    baseline = _parsed(source, candidates=(_member(source, "atom", 2, 3),))
    fresh = _parsed(
        source,
        wrappers=(v4.WrapperSpan("prefix", _span(source, 0, 2), _span(source, 2, 3)),),
        candidates=(_member(source, "broad", 0, 3),),
    )
    nodes, component = _first_component(source, fresh, baseline)
    witness = _witness("E2-wrapper-boundary", source, component)

    assert (
        v8._compatibility(
            component, (witness,), (witness, witness), nodes, fresh, baseline
        )
        == "veto:atomic-producer-contamination"
    )


def test_compatibility_vetoes_scope_change_outside_component() -> None:
    source = "AB"
    atom = _member(source, "atom", 0, 1)
    baseline = _parsed(
        source,
        candidates=(atom,),
        scopes=(v4.SharedScope("scope", "suffix", _span(source, 1, 2), (atom.id,)),),
    )
    fresh = _parsed(source, candidates=(_member(source, "other", 1, 2),))
    candidate_nodes = (
        v8._DeltaNode(
            1,
            "v5",
            "item_candidates",
            ((1, 2),),
            fresh.item_candidates[0],
            (_span(source, 1, 2),),
            (_span(source, 1, 2),),
        ),
        v8._DeltaNode(
            2, "v6", "item_candidates", ((0, 1),), atom, (atom.span,), (atom.span,)
        ),
    )
    component = v8._Component(1, frozenset({1, 2}), _span(source, 0, 2))
    witness = _witness("E6-priority-tail-rejection", source, component)

    assert (
        v8._compatibility(
            component, (witness,), (witness,), candidate_nodes, fresh, baseline
        )
        == "veto:scope-outside-closure"
    )


def test_compatibility_requires_witness_to_repair_its_local_structure() -> None:
    source = "doA"
    wrapper = v4.WrapperSpan("prefix", _span(source, 0, 2), _span(source, 2, 3))
    fresh = _parsed(source, wrappers=(wrapper,))
    baseline = _parsed(source)
    node = v8._DeltaNode(
        1,
        "v5",
        "wrappers",
        v8._wrapper_signature(wrapper),
        wrapper,
        (wrapper.marker_span, wrapper.content_span),
        (wrapper.content_span,),
    )
    component = v8._Component(1, frozenset({1}), _span(source, 0, 3))
    witness = _witness("E2-wrapper-boundary", source, component)

    assert (
        v8._compatibility(
            component, (witness,), (witness, witness), (node,), fresh, baseline
        )
        == "veto:unrepaired-E2"
    )


def test_delta_graph_keeps_disjoint_structures_in_separate_components() -> None:
    source = "doA;doB"
    a = _member(source, "a", 2, 3)
    b = _member(source, "b", 6, 7)
    fresh = _parsed(
        source,
        wrappers=(
            v4.WrapperSpan("prefix", _span(source, 0, 2), a.span),
            v4.WrapperSpan("prefix", _span(source, 4, 6), b.span),
        ),
        candidates=(a, b),
    )
    baseline = _parsed(
        source,
        candidates=(
            _member(source, "broad-a", 0, 3),
            _member(source, "broad-b", 4, 7),
        ),
    )
    _, components = _graph(source, baseline, fresh, baseline)

    assert len(components) == 2


def test_compatible_supported_component_defeats_overlapping_s2() -> None:
    source = "doA;doB"
    a = _member(source, "a", 2, 3)
    b = _member(source, "b", 6, 7)
    base = _parsed(source, candidates=(a, b))
    fresh = _parsed(
        source,
        wrappers=(
            v4.WrapperSpan("prefix", _span(source, 0, 2), a.span),
            v4.WrapperSpan("prefix", _span(source, 4, 6), b.span),
        ),
        candidates=(a, b),
    )
    baseline = _parsed(
        source,
        candidates=(
            _member(source, "broad-a", 0, 3),
            _member(source, "broad-b", 4, 7),
        ),
    )

    plan = v8._selection_plan(source, base, fresh, baseline)

    assert plan.decisions
    assert all(
        all(origin == "v5" for origin in decision.origins.values())
        for decision in plan.decisions.values()
    )


def test_rebuild_rebases_scope_targets_and_projects_once() -> None:
    source = "A或B"
    connector = _span(source, 1, 2)
    a = _member(source, "a", 0, 1)
    b = _member(source, "b", 2, 3)
    parsed = _parsed(
        source,
        labels=(v4.ConnectorLabel(connector, "surface"),),
        groups=(
            v4.CoordinationGroup("group", "surface", "synthetic", (connector,), (a, b)),
        ),
        scopes=(v4.SharedScope("scope", "suffix", b.span, (a.id, b.id)),),
        candidates=(
            _member(source, "candidate-a", 0, 1),
            _member(source, "candidate-b", 2, 3),
        ),
    )
    plan = v8._selection_plan(source, parsed, parsed, parsed)
    rebuilt = v8._rebuild(
        source, "skill", {"v4": parsed, "v5": parsed, "v6": parsed}, plan
    )
    extraction = v8.project_surface_items(rebuilt)
    known = {
        member.id for group in rebuilt.coordinations for member in group.members
    } | {candidate.id for candidate in rebuilt.item_candidates}

    assert all(
        set(scope.applies_to_member_ids) <= known for scope in rebuilt.shared_scopes
    )
    assert extraction.items == ("A", "B")
    assert rebuilt.rule_ids.count("v8.graph-projection-once") == 1
