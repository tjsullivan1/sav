# Episodes Go Through a Store, Not Straight to Disk

Generated Episodes are written to and read from an Episode Store, addressed by the Article,
Script Strategy, and Voice that produced them. Phase one implements that store as a local
directory; the intent is to add an Azure Storage backed implementation later without changing
callers.

Writing directly to a local path would be less code today, but the reuse behaviour that saves us
per-character text-to-speech spend is the same logic in both worlds, and it is the piece we would
otherwise rewrite when Episodes move to the cloud. Naming an Episode is the hard part, and doing
it now means the later change is a new implementation rather than a new concept.
