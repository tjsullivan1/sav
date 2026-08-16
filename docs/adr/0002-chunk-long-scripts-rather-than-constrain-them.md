# Chunk Long Scripts Rather Than Constrain Them

Narration Scripts routinely exceed the text-to-speech provider's per-request character cap
(10,000 for the higher-quality multilingual voice model, 40,000 for the faster ones). We split a
Script at paragraph boundaries into chunks sized to whichever model is active, synthesize each,
and stitch the audio into one Episode.

The alternative was to pick a model with a large cap and refuse anything longer, which is less
code but permanently ties voice quality to article length — the wrong axis to trade on. Chunking
costs us a stitching step and the audio tooling that implies, but it makes model choice a free
decision driven by how the Episode sounds.
