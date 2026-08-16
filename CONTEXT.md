# Blog to Podcast

Turns a public blog post into a listenable audio episode. This context covers how source text is
obtained, how it becomes something worth narrating, and what the listener ends up with.

## Language

**Article**:
The public blog post supplied as input, identified by its URL.
_Avoid_: blog, post, page, source

**Episode**:
The audio artifact produced from a single Article.
_Avoid_: podcast, output, recording, MP3

**Episode Request**:
The choices that define one Episode to be produced: which Article, which Script Strategy, and
which Voice. Distinct from the credentials needed to fulfil it, which are never part of a request.
_Avoid_: job, config, settings, params

**Voice**:
The speaker identity an Episode is narrated in.
_Avoid_: speaker, narrator, model

**Episode Store**:
Where Episodes are kept and looked up once produced, addressed by the Episode Request that
produced them. An Episode found in the store is served rather than generated again.
_Avoid_: cache, storage, bucket, library

**Script**:
The text that gets narrated to produce an Episode.
_Avoid_: summary, transcript, text, copy

**Script Strategy**:
The named approach used to turn an Article into a Script. The two strategies are Narration and
Summary; they are different operations, not two settings of one operation.
_Avoid_: mode, format, length

**Narration**:
A Script that follows the Article closely, cleaned up for speech rather than rewritten.
_Avoid_: verbatim, full text, read-aloud

**Summary**:
A Script that condenses the Article into a short retelling, discarding most of the source.
_Avoid_: digest, abstract, show notes, TL;DR
