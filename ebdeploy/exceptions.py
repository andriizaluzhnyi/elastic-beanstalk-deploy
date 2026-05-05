class DeployError(Exception):
    """Base deployment error."""
    pass


class ConfigError(DeployError):
    """Configuration error."""
    pass


class ArchiveError(DeployError):
    """Archive creation error."""
    pass


class S3Error(DeployError):
    """S3 upload error."""
    pass


class EBError(DeployError):
    """Elastic Beanstalk error."""
    pass


class STSError(DeployError):
    """STS temporary credentials error."""
    pass
