# ebdeploy

A lightweight Python library for automating deployments to **AWS Elastic Beanstalk**.

## Installation

```bash
pip install ebdeploy
# or from source:
pip install -e .
```

## Configuration

Run the interactive setup wizard to generate `.elasticbeanstalk/ebdeploy.yml`:

```bash
ebdeploy init
```

Or copy `ebdeploy.yml.example` → `.elasticbeanstalk/ebdeploy.yml` and fill in the values:

```yaml
app_name: d-sights-danone               # <project>-<client>
environment: d-sights-danone-stage      # <project>-<client>-<env>
s3_bucket: elasticbeanstalk-us-east-1-089747246458
s3_prefix: d-sights/stage/danone        # <project>/<env>/<client>
aws_region: us-east-1
aws_profile: my-aws-profile             # remove to use the default profile
```

All parameters can be overridden with `EB_*` environment variables:

| Variable          | Config field  |
|-------------------|---------------|
| `EB_APP_NAME`     | `app_name`    |
| `EB_ENVIRONMENT`  | `environment` |
| `EB_S3_BUCKET`    | `s3_bucket`   |
| `EB_S3_PREFIX`    | `s3_prefix`   |
| `EB_AWS_REGION`   | `aws_region`  |
| `EB_AWS_PROFILE`  | `aws_profile` |

### .ebignore

Create a `.ebignore` file in your project root to exclude files from the deployment archive. Uses the same glob syntax as `.gitignore`:

```plaintext
# .ebignore
tests/
*.log
docs/
.env.local
```

## CLI

```bash
# Interactive setup
ebdeploy init
ebdeploy init --reconfigure

# Full deploy (version = git SHA)
ebdeploy deploy

# Deploy with a custom version label
ebdeploy deploy --version v1.2.3

# Dry-run (build archive only, no AWS calls)
ebdeploy deploy --dry-run

# Show environment status
ebdeploy status

# Build archive only
ebdeploy package --output deploy.zip

# Override config via CLI flags
ebdeploy deploy --profile prod-profile --environment myapp-prod
```

## Makefile

Add to your `Makefile`:

```makefile
.PHONY: deploy deploy-dry status

deploy:
        ebdeploy deploy

deploy-dry:
        ebdeploy deploy --dry-run

status:
        ebdeploy status
```

## Python API

```python
from ebdeploy import Deployer, DeployConfig

cfg = DeployConfig.auto()          # reads ebdeploy.yml + ENV
deployer = Deployer(cfg)

# Full deploy
version = deployer.deploy()

# Dry-run
deployer.deploy(dry_run=True)

# Build archive only
deployer.package(output_path="deploy.zip")

# Environment status
info = deployer.status()
print(info["Status"], info["Health"])
```

## How it works

```plaintext
git rev-parse --short HEAD  →  version label (e.g. a1b2c3d)
        │
        ▼
git archive HEAD -o deploy.zip   (or zip with all files)
        │
        ▼
aws s3 cp deploy.zip s3://<bucket>/<project>/<env>/<client>/<version>.zip
        │
        ▼
aws elasticbeanstalk create-application-version
        │
        ▼
aws elasticbeanstalk update-environment
        │
        ▼
Poll every 15s → wait for Status=Ready ✓
```

## Tests

```bash
pip install -e ".[dev]"
pytest tests/ -v
```
