# AI Campus Core Parser v36 execution plan

V36 is based only on observable v35 failure classes and keeps DeepSeek thinking
disabled. Prompt v23, Schema v10, skill ontology v4, the four public JD inputs,
and their owner-reviewed labels remain unchanged.

Generic compatibility behavior:

- ignore an empty `skills` clause when it carries no semantic content;
- retain non-empty examples from an empty clause as `mention` values;
- normalize documented qualifier aliases and downgrade unsupported qualifier
  values to absence with an audit warning;
- preserve transport diagnostics when later Parser validation fails;
- enforce explicit source policy for responsibility sections, preferred
  sections, and weak `了解/认知/兴趣/热情` cues;
- normalize province-qualified city strings such as `广东省·深圳市` to `深圳`.

All new behavior is covered by offline tests and contains no company, case ID,
or expected skill-label exception. V36 uses a new manifest and new output paths;
v34 and v35 artifacts remain immutable.
