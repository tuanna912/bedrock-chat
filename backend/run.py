"""Shim module required for the AWS Lambda Web Adapter.

When the Lambda handler is configured as ``run.sh`` the Python
runtime attempts to import a module named ``run`` and look for
an attribute called ``sh``.  Without this file the import fails
during cold start, resulting in ``Runtime.ImportModuleError``.

The web adapter intercepts invocations via ``AWS_LAMBDA_EXEC_WRAPPER``,
so this handler should never be called.  If it is invoked directly
we return a 502 response to make the failure obvious without
raising another exception.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def sh(event: Dict[str, Any], _context: Any) -> Dict[str, Any]:
    """Fallback handler when the web adapter is bypassed."""
    logger.error(
        "Lambda handler 'run.sh' was invoked directly. "
        "Check the Lambda Web Adapter configuration."
    )
    return {
        "statusCode": 502,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(
            {
                "message": "Lambda Web Adapter bootstrap not initialized.",
                "detail": "See CloudWatch logs for more information.",
            }
        ),
    }
