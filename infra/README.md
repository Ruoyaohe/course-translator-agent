# Deployment

The compose file supplies local PostgreSQL, Redis, and S3-compatible storage. The current API defaults to its deterministic filesystem adapters so the end-to-end flow can be reviewed before cloud credentials are introduced.

For Alibaba Cloud Singapore, deploy the web and API images behind HTTPS/WSS, then replace the local adapters with RDS PostgreSQL, Redis, and OSS values. Set all variables from `.env.example` in the platform secret manager. Restrict inbound API traffic to the web origin, configure the GitHub OAuth callback to the public web URL, and use a repository-scoped deploy key for the Obsidian repository.

Never bake `.env`, a vault checkout, audio, or DashScope/GitHub credentials into either image.

