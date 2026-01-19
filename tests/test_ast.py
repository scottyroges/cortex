"""
Tests for AST Module

Tests tree-sitter parsing and language extractors.
"""

import pytest

from src.ast.models import (
    ClassInfo,
    DataContractInfo,
    FieldInfo,
    FileMetadata,
    FunctionSignature,
    ImportInfo,
    ParameterInfo,
)
from src.ast.parser import ASTParser, get_parser, EXTENSION_TO_LANGUAGE


# =============================================================================
# Phase 1: Parser Tests
# =============================================================================


class TestLanguageDetection:
    """Test language detection from file extensions."""

    def test_python_extensions(self):
        parser = get_parser()
        assert parser.detect_language("main.py") == "python"
        assert parser.detect_language("script.pyw") == "python"
        assert parser.detect_language("/path/to/module.py") == "python"

    def test_typescript_extensions(self):
        parser = get_parser()
        assert parser.detect_language("app.ts") == "typescript"
        assert parser.detect_language("component.tsx") == "tsx"
        assert parser.detect_language("index.js") == "typescript"  # JS uses TS parser
        assert parser.detect_language("App.jsx") == "tsx"

    def test_kotlin_extensions(self):
        parser = get_parser()
        assert parser.detect_language("Main.kt") == "kotlin"
        assert parser.detect_language("build.gradle.kts") == "kotlin"

    def test_unsupported_extensions(self):
        parser = get_parser()
        assert parser.detect_language("main.go") is None
        assert parser.detect_language("app.rs") is None
        assert parser.detect_language("readme.md") is None

    def test_is_supported(self):
        parser = get_parser()
        assert parser.is_supported("main.py")
        assert parser.is_supported("app.ts")
        assert parser.is_supported("Main.kt")
        assert not parser.is_supported("main.go")


class TestPythonParsing:
    """Test tree-sitter Python parsing."""

    def test_parse_simple_function(self):
        parser = get_parser()
        source = '''
def hello(name: str) -> str:
    """Say hello."""
    return f"Hello, {name}!"
'''
        tree = parser.parse(source, "python")
        assert tree is not None
        assert tree.root_node.type == "module"

    def test_parse_class(self):
        parser = get_parser()
        source = '''
class User:
    def __init__(self, name: str):
        self.name = name

    def greet(self) -> str:
        return f"Hello, {self.name}"
'''
        tree = parser.parse(source, "python")
        assert tree is not None
        # Find class_definition node
        class_nodes = [n for n in tree.root_node.children if n.type == "class_definition"]
        assert len(class_nodes) == 1

    def test_parse_imports(self):
        parser = get_parser()
        source = '''
import os
from pathlib import Path
from typing import Optional, List
'''
        tree = parser.parse(source, "python")
        assert tree is not None
        # Should have import statements
        import_nodes = [n for n in tree.root_node.children
                       if n.type in ("import_statement", "import_from_statement")]
        assert len(import_nodes) == 3

    def test_parse_syntax_error_graceful(self):
        """Parser should handle syntax errors gracefully."""
        parser = get_parser()
        source = '''
def broken(
    # Missing closing paren and body
'''
        tree = parser.parse(source, "python")
        # Tree-sitter still returns a tree, just with ERROR nodes
        assert tree is not None


class TestTypeScriptParsing:
    """Test tree-sitter TypeScript parsing."""

    def test_parse_interface(self):
        parser = get_parser()
        source = '''
interface User {
    id: string;
    name: string;
    email?: string;
}
'''
        tree = parser.parse(source, "typescript")
        assert tree is not None
        assert tree.root_node.type == "program"

    def test_parse_function(self):
        parser = get_parser()
        source = '''
export function greet(name: string): string {
    return `Hello, ${name}!`;
}
'''
        tree = parser.parse(source, "typescript")
        assert tree is not None

    def test_parse_class(self):
        parser = get_parser()
        source = '''
export class UserService {
    constructor(private db: Database) {}

    async getUser(id: string): Promise<User> {
        return this.db.find(id);
    }
}
'''
        tree = parser.parse(source, "typescript")
        assert tree is not None


class TestKotlinParsing:
    """Test tree-sitter Kotlin parsing."""

    def test_parse_data_class(self):
        parser = get_parser()
        source = '''
data class User(
    val id: String,
    val name: String,
    val email: String?
)
'''
        tree = parser.parse(source, "kotlin")
        assert tree is not None

    def test_parse_function(self):
        parser = get_parser()
        source = '''
fun greet(name: String): String {
    return "Hello, $name!"
}
'''
        tree = parser.parse(source, "kotlin")
        assert tree is not None


class TestParserSingleton:
    """Test that parser singleton works correctly."""

    def test_singleton_returns_same_instance(self):
        parser1 = get_parser()
        parser2 = get_parser()
        assert parser1 is parser2

    def test_parser_caches_languages(self):
        parser = get_parser()
        # Parse twice with same language
        tree1 = parser.parse("x = 1", "python")
        tree2 = parser.parse("y = 2", "python")
        assert tree1 is not None
        assert tree2 is not None
        # Should have cached the parser
        assert "python" in parser._parsers


# =============================================================================
# Model Tests
# =============================================================================


class TestFileMetadata:
    """Test FileMetadata model."""

    def test_get_export_list(self):
        metadata = FileMetadata(
            file_path="test.py",
            language="python",
            exports=["foo", "bar"],
            classes=[ClassInfo(name="MyClass")],
            functions=[
                FunctionSignature(name="my_func", is_method=False),
                FunctionSignature(name="method", is_method=True),  # Should be excluded
            ],
        )
        exports = metadata.get_export_list()
        assert "foo" in exports
        assert "bar" in exports
        assert "MyClass" in exports
        assert "my_func" in exports
        assert "method" not in exports  # Methods excluded

    def test_to_search_content(self):
        metadata = FileMetadata(
            file_path="src/auth/service.py",
            language="python",
            description="Handles user authentication with JWT tokens.",
            exports=["AuthService", "authenticate"],
            imports=[
                ImportInfo(module="jwt"),
                ImportInfo(module="src.models", names=["User"]),
            ],
        )
        content = metadata.to_search_content()
        assert "src/auth/service.py" in content
        assert "JWT tokens" in content
        assert "AuthService" in content
        assert "jwt" in content


class TestImportInfo:
    """Test ImportInfo model."""

    def test_simple_import(self):
        info = ImportInfo(module="os")
        assert info.module == "os"
        assert info.names == []
        assert info.is_external

    def test_from_import(self):
        info = ImportInfo(
            module="pathlib",
            names=["Path", "PurePath"],
            is_external=True,
        )
        assert info.module == "pathlib"
        assert "Path" in info.names

    def test_internal_import(self):
        info = ImportInfo(
            module="src.models",
            names=["User"],
            is_external=False,
        )
        assert not info.is_external


# =============================================================================
# Phase 2: Python Extractor Tests
# =============================================================================

# Import after models to avoid circular imports
from src.ast.extractors.python import PythonExtractor
from src.ast.extractors.base import get_extractor


class TestPythonExtractorImports:
    """Test Python import extraction."""

    def setup_method(self):
        self.extractor = PythonExtractor()
        self.parser = get_parser()

    def test_simple_import(self):
        source = "import os"
        tree = self.parser.parse(source, "python")
        imports = self.extractor.extract_imports(tree, source)

        assert len(imports) == 1
        assert imports[0].module == "os"
        assert imports[0].is_external

    def test_import_with_alias(self):
        source = "import numpy as np"
        tree = self.parser.parse(source, "python")
        imports = self.extractor.extract_imports(tree, source)

        assert len(imports) == 1
        assert imports[0].module == "numpy"
        assert imports[0].alias == "np"

    def test_from_import(self):
        source = "from pathlib import Path, PurePath"
        tree = self.parser.parse(source, "python")
        imports = self.extractor.extract_imports(tree, source)

        assert len(imports) == 1
        assert imports[0].module == "pathlib"
        assert "Path" in imports[0].names
        assert "PurePath" in imports[0].names

    def test_relative_import(self):
        source = "from .models import User"
        tree = self.parser.parse(source, "python")
        imports = self.extractor.extract_imports(tree, source)

        assert len(imports) == 1
        assert not imports[0].is_external  # Relative imports are internal

    def test_multiple_imports(self):
        source = '''
import os
import sys
from typing import Optional, List
from pathlib import Path
'''
        tree = self.parser.parse(source, "python")
        imports = self.extractor.extract_imports(tree, source)

        assert len(imports) == 4


class TestPythonExtractorExports:
    """Test Python export extraction."""

    def setup_method(self):
        self.extractor = PythonExtractor()
        self.parser = get_parser()

    def test_exports_with_all(self):
        source = '''
__all__ = ["foo", "Bar"]

def foo():
    pass

class Bar:
    pass

def _private():
    pass
'''
        tree = self.parser.parse(source, "python")
        exports = self.extractor.extract_exports(tree, source)

        assert exports == ["foo", "Bar"]

    def test_exports_without_all(self):
        source = '''
def public_func():
    pass

class PublicClass:
    pass

def _private_func():
    pass

class _PrivateClass:
    pass
'''
        tree = self.parser.parse(source, "python")
        exports = self.extractor.extract_exports(tree, source)

        assert "public_func" in exports
        assert "PublicClass" in exports
        assert "_private_func" not in exports
        assert "_PrivateClass" not in exports


class TestPythonExtractorFunctions:
    """Test Python function extraction."""

    def setup_method(self):
        self.extractor = PythonExtractor()
        self.parser = get_parser()

    def test_simple_function(self):
        source = '''
def greet(name: str) -> str:
    """Say hello."""
    return f"Hello, {name}!"
'''
        tree = self.parser.parse(source, "python")
        functions = self.extractor.extract_functions(tree, source)

        assert len(functions) == 1
        func = functions[0]
        assert func.name == "greet"
        assert func.return_type == "str"
        assert len(func.parameters) == 1
        assert func.parameters[0].name == "name"
        assert func.parameters[0].type_annotation == "str"
        assert "Say hello" in func.docstring

    def test_async_function(self):
        source = '''
async def fetch_data(url: str) -> dict:
    pass
'''
        tree = self.parser.parse(source, "python")
        functions = self.extractor.extract_functions(tree, source)

        assert len(functions) == 1
        assert functions[0].is_async

    def test_decorated_function(self):
        source = '''
@app.route("/api")
@authenticated
def api_handler():
    pass
'''
        tree = self.parser.parse(source, "python")
        functions = self.extractor.extract_functions(tree, source)

        assert len(functions) == 1
        assert "app.route" in functions[0].decorators
        assert "authenticated" in functions[0].decorators


class TestPythonExtractorClasses:
    """Test Python class extraction."""

    def setup_method(self):
        self.extractor = PythonExtractor()
        self.parser = get_parser()

    def test_simple_class(self):
        source = '''
class User:
    """User model."""

    def __init__(self, name: str):
        self.name = name

    def greet(self) -> str:
        return f"Hello, {self.name}"
'''
        tree = self.parser.parse(source, "python")
        classes = self.extractor.extract_classes(tree, source)

        assert len(classes) == 1
        cls = classes[0]
        assert cls.name == "User"
        assert "User model" in cls.docstring
        assert len(cls.methods) == 2
        assert cls.methods[0].name == "__init__"
        assert cls.methods[1].name == "greet"
        assert cls.methods[1].is_method

    def test_class_with_base(self):
        source = '''
class Admin(User):
    pass
'''
        tree = self.parser.parse(source, "python")
        classes = self.extractor.extract_classes(tree, source)

        assert len(classes) == 1
        assert "User" in classes[0].bases

    def test_dataclass(self):
        source = '''
@dataclass
class Point:
    x: int
    y: int
'''
        tree = self.parser.parse(source, "python")
        classes = self.extractor.extract_classes(tree, source)

        assert len(classes) == 1
        assert classes[0].is_dataclass


class TestPythonExtractorDataContracts:
    """Test Python data contract extraction."""

    def setup_method(self):
        self.extractor = PythonExtractor()
        self.parser = get_parser()

    def test_dataclass_contract(self):
        source = '''
@dataclass
class User:
    name: str
    age: int = 0
'''
        tree = self.parser.parse(source, "python")
        contracts = self.extractor.extract_data_contracts(tree, source)

        assert len(contracts) == 1
        contract = contracts[0]
        assert contract.name == "User"
        assert contract.contract_type == "dataclass"

    def test_pydantic_model(self):
        source = '''
class UserCreate(BaseModel):
    name: str
    email: str
'''
        tree = self.parser.parse(source, "python")
        contracts = self.extractor.extract_data_contracts(tree, source)

        assert len(contracts) == 1
        assert contracts[0].contract_type == "model"

    def test_regular_class_not_contract(self):
        source = '''
class Service:
    def do_something(self):
        pass
'''
        tree = self.parser.parse(source, "python")
        contracts = self.extractor.extract_data_contracts(tree, source)

        assert len(contracts) == 0


class TestPythonExtractorEntryPoints:
    """Test Python entry point detection."""

    def setup_method(self):
        self.extractor = PythonExtractor()
        self.parser = get_parser()

    def test_main_block(self):
        source = '''
def main():
    pass

if __name__ == "__main__":
    main()
'''
        tree = self.parser.parse(source, "python")
        entry_type = self.extractor.detect_entry_point(tree, source, "script.py")

        assert entry_type == "main"

    def test_fastapi_route(self):
        source = '''
from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def root():
    return {"message": "Hello"}
'''
        tree = self.parser.parse(source, "python")
        entry_type = self.extractor.detect_entry_point(tree, source, "api.py")

        assert entry_type == "api_route"

    def test_cli_with_click(self):
        source = '''
import click

@click.command()
def cli():
    pass
'''
        tree = self.parser.parse(source, "python")
        entry_type = self.extractor.detect_entry_point(tree, source, "cli.py")

        assert entry_type == "cli"


class TestPythonExtractorBarrel:
    """Test Python barrel file detection."""

    def setup_method(self):
        self.extractor = PythonExtractor()
        self.parser = get_parser()

    def test_barrel_init(self):
        source = '''
from .models import User, Post
from .services import UserService
'''
        tree = self.parser.parse(source, "python")
        is_barrel = self.extractor.detect_barrel(tree, source, "pkg/__init__.py")

        assert is_barrel

    def test_non_barrel_init(self):
        source = '''
from .models import User

def setup():
    pass
'''
        tree = self.parser.parse(source, "python")
        is_barrel = self.extractor.detect_barrel(tree, source, "pkg/__init__.py")

        assert not is_barrel

    def test_regular_file_not_barrel(self):
        source = '''
from .models import User
'''
        tree = self.parser.parse(source, "python")
        is_barrel = self.extractor.detect_barrel(tree, source, "pkg/module.py")

        assert not is_barrel


class TestPythonExtractorExtractAll:
    """Test the full extract_all method."""

    def setup_method(self):
        self.extractor = PythonExtractor()
        self.parser = get_parser()

    def test_extract_all_comprehensive(self):
        source = '''
"""Module docstring."""

from typing import Optional
from pathlib import Path

from .utils import helper


@dataclass
class Config:
    name: str
    debug: bool = False


def load_config(path: Path) -> Config:
    """Load configuration from file."""
    pass


class Service:
    def __init__(self, config: Config):
        self.config = config

    async def run(self) -> None:
        pass
'''
        tree = self.parser.parse(source, "python")
        metadata = self.extractor.extract_all(tree, source, "src/service.py")

        assert metadata.file_path == "src/service.py"
        assert metadata.language == "python"
        assert len(metadata.imports) == 3
        assert len(metadata.classes) == 2  # Config and Service
        assert len(metadata.functions) == 1  # load_config
        assert len(metadata.data_contracts) == 1  # Config is a dataclass


class TestExtractorRegistry:
    """Test the extractor registry."""

    def test_get_python_extractor(self):
        extractor = get_extractor("python")
        assert extractor is not None
        assert extractor.language == "python"

    def test_get_unknown_extractor(self):
        extractor = get_extractor("unknown")
        assert extractor is None


# =============================================================================
# Phase 3: Description Generator Tests
# =============================================================================

from unittest.mock import Mock, patch
from src.ast.description import (
    generate_description,
    generate_description_from_metadata,
    _fallback_description,
    DESCRIPTION_PROMPT,
)
from src.llm import LLMResponse


class TestFallbackDescription:
    """Test fallback description generation."""

    def test_with_exports(self):
        desc = _fallback_description(
            "src/auth/service.py",
            "python",
            ["AuthService", "authenticate", "verify_token"],
        )
        assert "src/auth/service.py" in desc
        assert "python" in desc
        assert "AuthService" in desc

    def test_with_many_exports(self):
        exports = ["a", "b", "c", "d", "e", "f", "g"]
        desc = _fallback_description("file.py", "python", exports)
        assert "+2 more" in desc  # 7 - 5 = 2 more

    def test_without_exports(self):
        desc = _fallback_description("empty.py", "python", [])
        assert "empty.py" in desc
        assert "python" in desc


class TestDescriptionGeneration:
    """Test LLM-based description generation."""

    def test_generate_with_mock_provider(self):
        """Test description generation with a mocked provider."""
        mock_provider = Mock()
        mock_provider.generate.return_value = LLMResponse(
            text="Handles user authentication with JWT tokens and bcrypt password hashing.",
            model="test-model",
            tokens_used=50,
        )

        source = '''
from jwt import encode, decode
from bcrypt import hashpw

class AuthService:
    def authenticate(self, username: str, password: str) -> str:
        """Authenticate user and return JWT token."""
        pass
'''
        desc = generate_description(
            file_path="src/auth/service.py",
            language="python",
            source_code=source,
            exports=["AuthService", "authenticate"],
            provider=mock_provider,
        )

        assert "JWT" in desc or "authentication" in desc.lower()
        mock_provider.generate.assert_called_once()

    def test_generate_falls_back_on_error(self):
        """Test that generation falls back on provider error."""
        mock_provider = Mock()
        mock_provider.generate.side_effect = Exception("API error")

        desc = generate_description(
            file_path="src/service.py",
            language="python",
            source_code="def foo(): pass",
            exports=["foo"],
            provider=mock_provider,
        )

        # Should return fallback
        assert "src/service.py" in desc
        assert "foo" in desc

    def test_generate_falls_back_on_short_response(self):
        """Test that very short responses trigger fallback."""
        mock_provider = Mock()
        mock_provider.generate.return_value = LLMResponse(
            text="Code file.",  # Too short
            model="test-model",
            tokens_used=5,
        )

        desc = generate_description(
            file_path="src/service.py",
            language="python",
            source_code="def foo(): pass",
            exports=["foo"],
            provider=mock_provider,
        )

        # Should return fallback due to short response
        assert "src/service.py" in desc

    def test_truncates_long_source(self):
        """Test that very long source code is truncated."""
        mock_provider = Mock()
        mock_provider.generate.return_value = LLMResponse(
            text="This is a long file with many functions.",
            model="test-model",
            tokens_used=50,
        )

        # Create source longer than 4000 chars
        long_source = "x = 1\n" * 1000  # ~6000 chars

        generate_description(
            file_path="big.py",
            language="python",
            source_code=long_source,
            exports=["x"],
            provider=mock_provider,
        )

        # Check that the prompt was called with truncated code
        call_args = mock_provider.generate.call_args[0][0]
        assert len(call_args) < len(long_source) + 500  # Prompt overhead


class TestDescriptionFromMetadata:
    """Test description generation from FileMetadata."""

    def test_generate_from_metadata(self):
        mock_provider = Mock()
        mock_provider.generate.return_value = LLMResponse(
            text="Test module with helper functions for validation.",
            model="test-model",
            tokens_used=30,
        )

        metadata = FileMetadata(
            file_path="src/utils.py",
            language="python",
            exports=["validate", "sanitize"],
            functions=[FunctionSignature(name="validate")],
        )

        desc = generate_description_from_metadata(
            metadata=metadata,
            source_code="def validate(): pass",
            provider=mock_provider,
        )

        assert "validation" in desc.lower() or "helper" in desc.lower()


class TestDescriptionPrompt:
    """Test the description prompt template."""

    def test_prompt_contains_required_elements(self):
        assert "{language}" in DESCRIPTION_PROMPT
        assert "{file_path}" in DESCRIPTION_PROMPT
        assert "{code}" in DESCRIPTION_PROMPT
        assert "search-optimized" in DESCRIPTION_PROMPT


# =============================================================================
# Phase 4: TypeScript Extractor Tests
# =============================================================================

from src.ast.extractors.typescript import TypeScriptExtractor


class TestTypeScriptExtractorImports:
    """Test TypeScript import extraction."""

    def setup_method(self):
        self.extractor = TypeScriptExtractor()
        self.parser = get_parser()

    def test_named_import(self):
        source = "import { Router, Request } from 'express';"
        tree = self.parser.parse(source, "typescript")
        imports = self.extractor.extract_imports(tree, source)

        assert len(imports) == 1
        assert imports[0].module == "express"
        assert "Router" in imports[0].names
        assert "Request" in imports[0].names
        assert imports[0].is_external

    def test_default_import(self):
        source = "import React from 'react';"
        tree = self.parser.parse(source, "typescript")
        imports = self.extractor.extract_imports(tree, source)

        assert len(imports) == 1
        assert imports[0].module == "react"
        assert "React" in imports[0].names

    def test_namespace_import(self):
        source = "import * as utils from './utils';"
        tree = self.parser.parse(source, "typescript")
        imports = self.extractor.extract_imports(tree, source)

        assert len(imports) == 1
        assert imports[0].module == "./utils"
        assert imports[0].alias == "utils"
        assert "*" in imports[0].names
        assert not imports[0].is_external

    def test_type_import(self):
        source = "import type { User } from './types';"
        tree = self.parser.parse(source, "typescript")
        imports = self.extractor.extract_imports(tree, source)

        assert len(imports) == 1
        assert imports[0].module == "./types"
        assert "User" in imports[0].names

    def test_relative_import(self):
        source = "import { helper } from '../utils/helper';"
        tree = self.parser.parse(source, "typescript")
        imports = self.extractor.extract_imports(tree, source)

        assert len(imports) == 1
        assert not imports[0].is_external


class TestTypeScriptExtractorExports:
    """Test TypeScript export extraction."""

    def setup_method(self):
        self.extractor = TypeScriptExtractor()
        self.parser = get_parser()

    def test_export_interface(self):
        source = """
export interface User {
    id: string;
    name: string;
}
"""
        tree = self.parser.parse(source, "typescript")
        exports = self.extractor.extract_exports(tree, source)

        assert "User" in exports

    def test_export_class(self):
        source = """
export class UserService {
    getUser(id: string): User { return null; }
}
"""
        tree = self.parser.parse(source, "typescript")
        exports = self.extractor.extract_exports(tree, source)

        assert "UserService" in exports

    def test_export_function(self):
        source = """
export function createUser(name: string): User {
    return { name };
}
"""
        tree = self.parser.parse(source, "typescript")
        exports = self.extractor.extract_exports(tree, source)

        assert "createUser" in exports

    def test_export_const(self):
        source = "export const API_URL = 'https://api.example.com';"
        tree = self.parser.parse(source, "typescript")
        exports = self.extractor.extract_exports(tree, source)

        assert "API_URL" in exports

    def test_export_default_not_counted_as_regular(self):
        source = """
export default class App {}
"""
        tree = self.parser.parse(source, "typescript")
        exports = self.extractor.extract_exports(tree, source)

        # Default exports are tracked separately
        assert "App" in exports


class TestTypeScriptExtractorDataContracts:
    """Test TypeScript data contract extraction."""

    def setup_method(self):
        self.extractor = TypeScriptExtractor()
        self.parser = get_parser()

    def test_interface_contract(self):
        source = """
interface UserDTO {
    id: string;
    name: string;
    email?: string;
}
"""
        tree = self.parser.parse(source, "typescript")
        contracts = self.extractor.extract_data_contracts(tree, source)

        assert len(contracts) == 1
        contract = contracts[0]
        assert contract.name == "UserDTO"
        assert contract.contract_type == "interface"
        assert len(contract.fields) == 3
        assert contract.fields[0].name == "id"
        assert contract.fields[2].optional  # email is optional

    def test_type_alias_contract(self):
        source = "type UserId = string;"
        tree = self.parser.parse(source, "typescript")
        contracts = self.extractor.extract_data_contracts(tree, source)

        assert len(contracts) == 1
        assert contracts[0].name == "UserId"
        assert contracts[0].contract_type == "type"

    def test_enum_contract(self):
        source = """
enum Status {
    Active = 'active',
    Inactive = 'inactive'
}
"""
        tree = self.parser.parse(source, "typescript")
        contracts = self.extractor.extract_data_contracts(tree, source)

        assert len(contracts) == 1
        contract = contracts[0]
        assert contract.name == "Status"
        assert contract.contract_type == "enum"
        assert len(contract.fields) == 2


class TestTypeScriptExtractorFunctions:
    """Test TypeScript function extraction."""

    def setup_method(self):
        self.extractor = TypeScriptExtractor()
        self.parser = get_parser()

    def test_simple_function(self):
        source = """
function greet(name: string): string {
    return \`Hello, \${name}!\`;
}
"""
        tree = self.parser.parse(source, "typescript")
        functions = self.extractor.extract_functions(tree, source)

        assert len(functions) == 1
        func = functions[0]
        assert func.name == "greet"
        assert func.return_type == "string"
        assert len(func.parameters) == 1
        assert func.parameters[0].name == "name"

    def test_async_function(self):
        source = """
async function fetchData(url: string): Promise<Response> {
    return fetch(url);
}
"""
        tree = self.parser.parse(source, "typescript")
        functions = self.extractor.extract_functions(tree, source)

        assert len(functions) == 1
        assert functions[0].is_async

    def test_exported_arrow_function(self):
        source = "export const add = (a: number, b: number): number => a + b;"
        tree = self.parser.parse(source, "typescript")
        functions = self.extractor.extract_functions(tree, source)

        assert len(functions) == 1
        func = functions[0]
        assert func.name == "add"
        assert len(func.parameters) == 2


class TestTypeScriptExtractorClasses:
    """Test TypeScript class extraction."""

    def setup_method(self):
        self.extractor = TypeScriptExtractor()
        self.parser = get_parser()

    def test_simple_class(self):
        source = """
class UserService {
    constructor(private db: Database) {}

    async getUser(id: string): Promise<User> {
        return this.db.find(id);
    }

    createUser(name: string): User {
        return { name };
    }
}
"""
        tree = self.parser.parse(source, "typescript")
        classes = self.extractor.extract_classes(tree, source)

        assert len(classes) == 1
        cls = classes[0]
        assert cls.name == "UserService"
        assert len(cls.methods) == 3  # constructor, getUser, createUser

    def test_class_with_extends(self):
        source = """
class Admin extends User {
    role: string = 'admin';
}
"""
        tree = self.parser.parse(source, "typescript")
        classes = self.extractor.extract_classes(tree, source)

        assert len(classes) == 1
        assert "User" in classes[0].bases

    def test_class_with_implements(self):
        source = """
class UserService implements IUserService {
    getUser(id: string): User { return null; }
}
"""
        tree = self.parser.parse(source, "typescript")
        classes = self.extractor.extract_classes(tree, source)

        assert len(classes) == 1
        assert "IUserService" in classes[0].bases


class TestTypeScriptExtractorEntryPoints:
    """Test TypeScript entry point detection."""

    def setup_method(self):
        self.extractor = TypeScriptExtractor()
        self.parser = get_parser()

    def test_express_route(self):
        source = """
import { Router } from 'express';
const router = Router();
router.get('/users', (req, res) => {});
export default router;
"""
        tree = self.parser.parse(source, "typescript")
        entry_type = self.extractor.detect_entry_point(tree, source, "routes/users.ts")

        assert entry_type == "api_route"

    def test_cli_with_commander(self):
        source = """
import { program } from 'commander';
program.option('-n, --name <name>', 'Your name');
program.parse();
"""
        tree = self.parser.parse(source, "typescript")
        entry_type = self.extractor.detect_entry_point(tree, source, "cli.ts")

        assert entry_type == "cli"


class TestTypeScriptExtractorBarrel:
    """Test TypeScript barrel file detection."""

    def setup_method(self):
        self.extractor = TypeScriptExtractor()
        self.parser = get_parser()

    def test_barrel_file(self):
        source = """
export * from './user';
export * from './post';
export { default as config } from './config';
"""
        tree = self.parser.parse(source, "typescript")
        is_barrel = self.extractor.detect_barrel(tree, source, "src/index.ts")

        assert is_barrel

    def test_non_barrel_index(self):
        source = """
export * from './types';

export function setup(): void {
    console.log('Setup');
}
"""
        tree = self.parser.parse(source, "typescript")
        is_barrel = self.extractor.detect_barrel(tree, source, "src/index.ts")

        assert not is_barrel  # Has own code

    def test_regular_file_not_barrel(self):
        source = "export * from './types';"
        tree = self.parser.parse(source, "typescript")
        is_barrel = self.extractor.detect_barrel(tree, source, "src/user.ts")

        assert not is_barrel  # Not an index file


class TestTypeScriptExtractorRegistry:
    """Test that TypeScript extractor is registered."""

    def test_get_typescript_extractor(self):
        extractor = get_extractor("typescript")
        assert extractor is not None
        assert extractor.language == "typescript"


# =============================================================================
# Phase 5: Kotlin Extractor Tests
# =============================================================================

from src.ast.extractors.kotlin import KotlinExtractor


class TestKotlinExtractorImports:
    """Test Kotlin import extraction."""

    def setup_method(self):
        self.extractor = KotlinExtractor()
        self.parser = get_parser()

    def test_simple_import(self):
        source = "import kotlinx.coroutines.flow.Flow"
        tree = self.parser.parse(source, "kotlin")
        imports = self.extractor.extract_imports(tree, source)

        assert len(imports) == 1
        assert imports[0].module == "kotlinx.coroutines.flow.Flow"
        assert imports[0].is_external

    def test_multiple_imports(self):
        source = """
import com.example.models.User
import kotlinx.coroutines.launch
"""
        tree = self.parser.parse(source, "kotlin")
        imports = self.extractor.extract_imports(tree, source)

        assert len(imports) == 2


class TestKotlinExtractorDataContracts:
    """Test Kotlin data contract extraction."""

    def setup_method(self):
        self.extractor = KotlinExtractor()
        self.parser = get_parser()

    def test_data_class_contract(self):
        source = """
data class User(
    val id: String,
    val name: String,
    val email: String? = null
)
"""
        tree = self.parser.parse(source, "kotlin")
        contracts = self.extractor.extract_data_contracts(tree, source)

        assert len(contracts) == 1
        contract = contracts[0]
        assert contract.name == "User"
        assert contract.contract_type == "dataclass"
        assert len(contract.fields) == 3
        assert contract.fields[0].name == "id"
        assert contract.fields[2].name == "email"
        assert contract.fields[2].optional

    def test_sealed_class_contract(self):
        source = """
sealed class Result<out T>
"""
        tree = self.parser.parse(source, "kotlin")
        contracts = self.extractor.extract_data_contracts(tree, source)

        assert len(contracts) == 1
        assert contracts[0].name == "Result"
        assert contracts[0].contract_type == "sealed_class"

    def test_interface_contract(self):
        source = """
interface UserRepository {
    suspend fun getUser(id: String): User?
}
"""
        tree = self.parser.parse(source, "kotlin")
        contracts = self.extractor.extract_data_contracts(tree, source)

        assert len(contracts) == 1
        assert contracts[0].name == "UserRepository"
        assert contracts[0].contract_type == "interface"


class TestKotlinExtractorFunctions:
    """Test Kotlin function extraction."""

    def setup_method(self):
        self.extractor = KotlinExtractor()
        self.parser = get_parser()

    def test_simple_function(self):
        source = """
fun greet(name: String): String {
    return "Hello, $name!"
}
"""
        tree = self.parser.parse(source, "kotlin")
        functions = self.extractor.extract_functions(tree, source)

        assert len(functions) == 1
        func = functions[0]
        assert func.name == "greet"
        assert func.return_type == "String"
        assert len(func.parameters) == 1
        assert func.parameters[0].name == "name"

    def test_suspend_function(self):
        source = """
suspend fun fetchData(url: String): Response {
    return client.get(url)
}
"""
        tree = self.parser.parse(source, "kotlin")
        functions = self.extractor.extract_functions(tree, source)

        assert len(functions) == 1
        assert functions[0].is_async  # suspend = async

    def test_main_function(self):
        source = """
fun main() {
    println("Hello")
}
"""
        tree = self.parser.parse(source, "kotlin")
        functions = self.extractor.extract_functions(tree, source)

        assert len(functions) == 1
        assert functions[0].name == "main"


class TestKotlinExtractorClasses:
    """Test Kotlin class extraction."""

    def setup_method(self):
        self.extractor = KotlinExtractor()
        self.parser = get_parser()

    def test_simple_class(self):
        source = """
class UserService(private val repo: UserRepository) {
    suspend fun findUser(id: String): User? {
        return repo.getUser(id)
    }
}
"""
        tree = self.parser.parse(source, "kotlin")
        classes = self.extractor.extract_classes(tree, source)

        assert len(classes) == 1
        cls = classes[0]
        assert cls.name == "UserService"
        assert len(cls.methods) == 1
        assert cls.methods[0].name == "findUser"
        assert cls.methods[0].is_async

    def test_data_class(self):
        source = """
data class Point(val x: Int, val y: Int)
"""
        tree = self.parser.parse(source, "kotlin")
        classes = self.extractor.extract_classes(tree, source)

        assert len(classes) == 1
        assert classes[0].is_dataclass


class TestKotlinExtractorEntryPoints:
    """Test Kotlin entry point detection."""

    def setup_method(self):
        self.extractor = KotlinExtractor()
        self.parser = get_parser()

    def test_main_function_entry(self):
        source = """
fun main(args: Array<String>) {
    println("Hello")
}
"""
        tree = self.parser.parse(source, "kotlin")
        entry_type = self.extractor.detect_entry_point(tree, source, "Main.kt")

        assert entry_type == "main"


class TestKotlinExtractorRegistry:
    """Test that Kotlin extractor is registered."""

    def test_get_kotlin_extractor(self):
        extractor = get_extractor("kotlin")
        assert extractor is not None
        assert extractor.language == "kotlin"
