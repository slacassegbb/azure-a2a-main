# Contributing to ServiceNow MCP Server

Thank you for considering contributing to the ServiceNow MCP Server! This document provides guidelines and instructions for contributing to this project.

## Code of Conduct

By participating in this project, you agree to abide by our code of conduct. Please be respectful and considerate of others.

## How to Contribute

### Reporting Bugs

If you find a bug, please create an issue on GitHub with the following information:

- A clear, descriptive title
- A detailed description of the issue
- Steps to reproduce the bug
- Expected behavior
- Actual behavior
- Screenshots (if applicable)
- Environment information (OS, Python version, etc.)

### Suggesting Enhancements

If you have an idea for an enhancement, please create an issue on GitHub with the following information:

- A clear, descriptive title
- A detailed description of the enhancement
- Any relevant examples or mockups
- Why this enhancement would be useful

### Pull Requests

1. Fork the repository
2. Create a new branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Run the tests (`pytest`)
5. Commit your changes (`git commit -m 'Add some amazing feature'`)
6. Push to the branch (`git push origin feature/amazing-feature`)
7. Open a Pull Request

## Development Setup

1. Clone the repository
   ```bash
   git clone https://github.com/michaelbuckner/servicenow-mcp.git
   cd servicenow-mcp
   ```

2. Create a virtual environment
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. Install development dependencies
   ```bash
   pip install -e ".[dev]"
   ```

4. Create a `.env` file with your ServiceNow credentials (see `.env.example`)

5. Run the tests
   ```bash
   pytest
   ```

## Coding Standards

- Follow PEP 8 style guide
- Use type hints
- Write docstrings for all functions, classes, and methods
- Write tests for all new features and bug fixes

## Testing

- All tests should be written using pytest
- Run tests with `pytest`
- Ensure all tests pass before submitting a pull request

## Documentation

- Update the README.md with any necessary changes
- Document all new features and changes in the code

## License

By contributing to this project, you agree that your contributions will be licensed under the project's MIT License.
