"""Package installation configuration."""

import re
from setuptools import find_packages, setup


def _get_version():
    with open("src/app/__init__.py") as f:
        match = re.search(r"^__version__ = ['\"]([^'\"]+)['\"]", f.read(), re.M)
    if not match:
        raise RuntimeError("Version not found in src/app/__init__.py")
    return match.group(1)


setup(
    name="opensearch-rag",
    version=_get_version(),
    description="Multi-tenant RAG application with OpenSearch, Ollama and LDAP",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    python_requires=">=3.10",
    install_requires=[
        "langchain-community>=0.3.0",
        "langchain-core>=0.3.0",
        "langchain-text-splitters>=0.3.0",
        "langchain-ollama>=0.3.0",
        "langchain-aws>=0.2.0",
        "opensearch-py>=2.3.1",
        "python-dotenv>=1.0.0",
        "pydantic>=2.0.0",
        "PyMuPDF>=1.23.0",
        "redis>=5.0.1",
        "transformers>=4.40.0",
        "fastapi>=0.115.0",
        "uvicorn[standard]>=0.32.0",
        "jinja2>=3.1.0",
        "python-multipart>=0.0.12",
        "ldap3>=2.9.1",
        "sqlalchemy[asyncio]>=2.0.0",
        "asyncpg>=0.29.0",
        "alembic>=1.13.0",
        "bcrypt>=4.0.0",
        "slowapi>=0.1.9",
    ],
    extras_require={
        "dev": [
            "pytest>=7.0.0",
            "pytest-asyncio>=0.23.0",
            "black>=23.0.0",
            "ruff>=0.1.0",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
)
