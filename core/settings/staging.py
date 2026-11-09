"""Settings de staging.

Herda as configurações de produção, mas marca o ambiente antes do import para
que ``prod.py`` aplique os defaults de staging (domínio da API, origem Netlify
e HSTS desligado). Todo o restante continua sobrescrevível por variáveis de
ambiente no ``.env.staging``.
"""

import os

os.environ.setdefault("ENVIRONMENT", "staging")

from .prod import *  # noqa: E402,F401,F403
