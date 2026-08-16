# Two Script Strategies, Not a Length Parameter

Turning an Article into a Script can mean two different things: reading it nearly as written, or
condensing it into a short retelling. We model these as two named Script Strategies — Narration
and Summary — rather than one prompt with a target character count.

Collapsing them into a length dial looked simpler, but a single "rewrite this in N characters"
prompt degrades into mushy half-summaries at long lengths, and it forces an LLM rewrite even when
the goal is faithfulness. Narration is mostly a cleanup problem, not a generation problem, so
keeping it separate lets it stay cheap, fast, and true to the source.
