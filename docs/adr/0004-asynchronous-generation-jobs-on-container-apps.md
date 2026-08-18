# Asynchronous Generation Jobs on Container Apps

Episode generation becomes a durable Generation Job submitted to a FastAPI Container App and
performed by a separate queue-scaled Container Apps worker. Clients receive `202 Accepted` and
poll the Job rather than holding a synchronous connection, because Article retrieval, Script
generation, synthesis, and stitching can outlast request limits and must survive reloads or
retries.
