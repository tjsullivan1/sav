# Azure Storage Is the Cloud Episode Store

Azure Storage Queue delivers Generation Jobs, Table Storage records Job and Episode metadata, and
Blob Storage retains completed audio and Scripts. This replaces the local Episode Store with a
right-sized, low-operations cloud implementation while preserving the same Episode identity and
revision behavior; a relational database is deferred until query or concurrency needs justify it.
