# infra

Configuration for the supporting tools the project uses but did not build: PostgreSQL for
records, Qdrant for vectors, RabbitMQ for passing work between services, and Nginx in front
of everything.

These are started by docker-compose.yml at the root. Nothing here is application code.

- `rabbitmq/rabbitmq.conf` — broker settings for the segment queue (OMNI-311). Credentials come
  from `.env`; the queue itself is declared by the services, not here.
