"""Package installation configuration."""

from setuptools import find_packages, setup

setup(
    name='langchain-opensearch-rag',
    version='0.1.0',
    description='LangChain RAG application with OpenSearch',
    author='euphonie',
    author_email='your.email@example.com',
    packages=find_packages(where='src'),
    package_dir={'': 'src'},
    python_requires='>=3.10',
    install_requires=[
        'langchain-community>=0.3.0',
        'langchain-core>=0.3.0',
        'langchain-text-splitters>=0.3.0',
        'langchain-ollama>=0.3.0',
        'langchain-aws>=0.2.0',
        'opensearch-py>=2.3.1',
        'gradio>=5.0.0',
        'python-dotenv>=1.0.0',
        'pydantic>=2.0.0',
        'PyMuPDF>=1.23.0',
        'redis>=5.0.1',
    ],
    extras_require={
        'dev': [
            'pytest>=7.0.0',
            'pytest-cov>=4.0.0',
            'black>=23.0.0',
            'ruff>=0.1.0',
            'mypy>=1.0.0',
        ],
    },
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Developers',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.12',
    ],
)
