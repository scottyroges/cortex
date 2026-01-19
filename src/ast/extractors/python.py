"""
Python AST Extractor

Extracts structured metadata from Python source files using tree-sitter.
"""

from pathlib import Path
from typing import Optional

from tree_sitter import Node, Tree

from src.ast.extractors.base import LanguageExtractor, register_extractor
from src.ast.models import (
    ClassInfo,
    DataContractInfo,
    FieldInfo,
    FunctionSignature,
    ImportInfo,
    ParameterInfo,
    TriggerInfo,
)


class PythonExtractor(LanguageExtractor):
    """Extracts metadata from Python source files."""

    @property
    def language(self) -> str:
        return "python"

    def extract_imports(self, tree: Tree, source: str) -> list[ImportInfo]:
        """Extract import and from...import statements."""
        imports = []
        root = tree.root_node

        # Handle: import x, import x as y, import x.y.z
        for node in self.walk_tree(root, "import_statement"):
            # Check for aliased imports first
            for aliased in self.find_children(node, "aliased_import"):
                name_node = self.find_child(aliased, "dotted_name")
                if name_node:
                    module = self.get_node_text(name_node, source)
                    # The alias is the identifier child (not the dotted_name)
                    alias = None
                    for child in aliased.children:
                        if child.type == "identifier":
                            alias = self.get_node_text(child, source)
                            break
                    imports.append(ImportInfo(
                        module=module,
                        alias=alias,
                        is_external=self._is_external_module(module),
                    ))

            # Non-aliased imports: direct dotted_name children
            for name_node in self.find_children(node, "dotted_name"):
                module = self.get_node_text(name_node, source)
                imports.append(ImportInfo(
                    module=module,
                    is_external=self._is_external_module(module),
                ))

        # Handle: from x import y, from x import y as z, from x import *
        for node in self.walk_tree(root, "import_from_statement"):
            # Get the module part
            module = ""
            relative_import = self.find_child(node, "relative_import")
            if relative_import:
                # Relative import like "from .models import X" or "from . import X"
                module = self.get_node_text(relative_import, source)
            else:
                # Regular import - first dotted_name is the module
                for child in node.children:
                    if child.type == "dotted_name":
                        module = self.get_node_text(child, source)
                        break

            # Get imported names - all dotted_names after 'import' keyword
            names = []
            found_import_keyword = False
            for child in node.children:
                if child.type == "import":
                    found_import_keyword = True
                elif found_import_keyword:
                    if child.type == "dotted_name":
                        names.append(self.get_node_text(child, source))
                    elif child.type == "aliased_import":
                        name_node = self.find_child(child, "dotted_name")
                        if name_node:
                            names.append(self.get_node_text(name_node, source))
                    elif child.type == "wildcard_import":
                        names.append("*")

            if names or module:
                imports.append(ImportInfo(
                    module=module,
                    names=names,
                    is_external=self._is_external_module(module),
                ))

        return imports

    def extract_exports(self, tree: Tree, source: str) -> list[str]:
        """
        Extract exported symbols.

        Python doesn't have explicit exports, so we return:
        1. Items in __all__ if defined
        2. Otherwise, public module-level symbols (not starting with _)
        """
        root = tree.root_node

        # Check for __all__ definition
        for node in self.walk_tree(root, "assignment"):
            left = self.find_child(node, "identifier")
            if left and self.get_node_text(left, source) == "__all__":
                # Extract list items
                list_node = self.find_child(node, "list")
                if list_node:
                    exports = []
                    for string_node in self.walk_tree(list_node, "string"):
                        text = self.get_node_text(string_node, source)
                        # Remove quotes
                        exports.append(text.strip("'\""))
                    return exports

        # No __all__, return public symbols
        exports = []

        # Module-level functions
        for node in root.children:
            if node.type == "function_definition":
                name_node = self.find_child(node, "identifier")
                if name_node:
                    name = self.get_node_text(name_node, source)
                    if not name.startswith("_"):
                        exports.append(name)

            elif node.type == "class_definition":
                name_node = self.find_child(node, "identifier")
                if name_node:
                    name = self.get_node_text(name_node, source)
                    if not name.startswith("_"):
                        exports.append(name)

            elif node.type == "decorated_definition":
                # Decorated function or class
                inner = self.find_child(node, "function_definition") or \
                        self.find_child(node, "class_definition")
                if inner:
                    name_node = self.find_child(inner, "identifier")
                    if name_node:
                        name = self.get_node_text(name_node, source)
                        if not name.startswith("_"):
                            exports.append(name)

        return exports

    def extract_classes(self, tree: Tree, source: str) -> list[ClassInfo]:
        """Extract class definitions."""
        classes = []
        root = tree.root_node

        for node in self._get_class_nodes(root):
            class_info = self._extract_class(node, source)
            if class_info:
                classes.append(class_info)

        return classes

    def extract_functions(self, tree: Tree, source: str) -> list[FunctionSignature]:
        """Extract top-level function definitions (not methods)."""
        functions = []
        root = tree.root_node

        for node in root.children:
            func_node = None
            decorators = []
            triggers = []

            if node.type == "function_definition":
                func_node = node
            elif node.type == "decorated_definition":
                func_node = self.find_child(node, "function_definition")
                decorators = self._extract_decorators(node, source)
                triggers = self._extract_triggers(node, source)

            if func_node:
                sig = self._extract_function_signature(func_node, source)
                if sig:
                    sig.decorators = decorators
                    sig.triggers = triggers
                    functions.append(sig)

        return functions

    def extract_data_contracts(self, tree: Tree, source: str) -> list[DataContractInfo]:
        """Extract data contracts (dataclasses, Pydantic models, TypedDict)."""
        contracts = []
        root = tree.root_node

        for node in self._get_class_nodes(root):
            contract = self._try_extract_data_contract(node, source)
            if contract:
                contracts.append(contract)

        return contracts

    def detect_entry_point(self, tree: Tree, source: str, file_path: str) -> Optional[str]:
        """Detect if this is an entry point file."""
        root = tree.root_node
        path = Path(file_path)

        # Check for if __name__ == "__main__"
        for node in self.walk_tree(root, "if_statement"):
            condition = self.find_child(node, "comparison_operator")
            if condition:
                text = self.get_node_text(condition, source)
                if "__name__" in text and "__main__" in text:
                    return "main"

        # Check for CLI frameworks
        imports = self.extract_imports(tree, source)
        import_modules = {i.module for i in imports}

        if "click" in import_modules or "typer" in import_modules:
            return "cli"

        if "argparse" in import_modules:
            return "cli"

        # Check for web frameworks (FastAPI, Flask, etc.)
        if "fastapi" in import_modules:
            # Look for FastAPI() or APIRouter()
            if "FastAPI" in source or "APIRouter" in source:
                return "api_route"

        if "flask" in import_modules:
            if "Flask(" in source or "@app.route" in source or "@bp.route" in source:
                return "api_route"

        # Check for common main file names
        if path.name in ("main.py", "app.py", "run.py", "cli.py"):
            return "main"

        # Entry point script
        if path.name == "__main__.py":
            return "main"

        return None

    def detect_barrel(self, tree: Tree, source: str, file_path: str) -> bool:
        """Detect if this is a barrel file (re-exports only)."""
        path = Path(file_path)

        # Only __init__.py can be barrel files in Python
        if path.name != "__init__.py":
            return False

        root = tree.root_node
        has_imports = False
        has_real_code = False

        for node in root.children:
            if node.type in ("import_statement", "import_from_statement"):
                has_imports = True
            elif node.type == "expression_statement":
                # Check if it's __all__ or a docstring
                child = node.children[0] if node.children else None
                if child:
                    if child.type == "string":
                        continue  # Docstring
                    elif child.type == "assignment":
                        left = self.find_child(child, "identifier")
                        if left and self.get_node_text(left, source) == "__all__":
                            continue  # __all__ definition
                has_real_code = True
            elif node.type in ("function_definition", "class_definition",
                               "decorated_definition"):
                has_real_code = True
            elif node.type == "comment":
                continue

        # Barrel if has imports but no real code
        return has_imports and not has_real_code

    # -------------------------------------------------------------------------
    # Private helper methods
    # -------------------------------------------------------------------------

    def _is_external_module(self, module: str) -> bool:
        """Check if a module is external (not a relative import)."""
        if not module:
            return False
        if module.startswith("."):
            return False
        # Check for common internal patterns
        if module.startswith("src.") or module.startswith("src/"):
            return False
        return True

    def _get_class_nodes(self, root: Node) -> list[Node]:
        """Get all class definition nodes (including decorated)."""
        nodes = []
        for node in root.children:
            if node.type == "class_definition":
                nodes.append(node)
            elif node.type == "decorated_definition":
                class_node = self.find_child(node, "class_definition")
                if class_node:
                    nodes.append(node)
        return nodes

    def _extract_class(self, node: Node, source: str) -> Optional[ClassInfo]:
        """Extract class information from a class_definition node."""
        class_node = node
        decorators = []

        if node.type == "decorated_definition":
            class_node = self.find_child(node, "class_definition")
            decorators = self._extract_decorators(node, source)
            if not class_node:
                return None

        name_node = self.find_child(class_node, "identifier")
        if not name_node:
            return None

        name = self.get_node_text(name_node, source)

        # Extract base classes
        bases = []
        arg_list = self.find_child(class_node, "argument_list")
        if arg_list:
            for child in arg_list.children:
                if child.type == "identifier":
                    bases.append(self.get_node_text(child, source))
                elif child.type == "attribute":
                    bases.append(self.get_node_text(child, source))

        # Extract methods
        methods = []
        body = self.find_child(class_node, "block")
        if body:
            for child in body.children:
                if child.type == "function_definition":
                    sig = self._extract_function_signature(child, source)
                    if sig:
                        sig.is_method = True
                        methods.append(sig)
                elif child.type == "decorated_definition":
                    func = self.find_child(child, "function_definition")
                    if func:
                        sig = self._extract_function_signature(func, source)
                        if sig:
                            sig.is_method = True
                            sig.decorators = self._extract_decorators(child, source)
                            methods.append(sig)

        # Extract docstring
        docstring = self._extract_docstring(class_node, source)

        # Check for dataclass/pydantic
        is_dataclass = "dataclass" in decorators or "dataclasses.dataclass" in decorators
        is_pydantic = "BaseModel" in bases or "pydantic.BaseModel" in bases

        return ClassInfo(
            name=name,
            bases=bases,
            methods=methods,
            decorators=decorators,
            docstring=docstring,
            is_dataclass=is_dataclass,
            is_pydantic=is_pydantic,
        )

    def _extract_function_signature(self, node: Node, source: str) -> Optional[FunctionSignature]:
        """Extract function signature from a function_definition node."""
        name_node = self.find_child(node, "identifier")
        if not name_node:
            return None

        name = self.get_node_text(name_node, source)

        # Check for async
        is_async = any(c.type == "async" for c in node.children)

        # Extract parameters
        params = []
        params_node = self.find_child(node, "parameters")
        if params_node:
            params = self._extract_parameters(params_node, source)

        # Extract return type
        return_type = None
        for child in node.children:
            if child.type == "type":
                return_type = self.get_node_text(child, source)
                break

        # Extract docstring
        docstring = self._extract_docstring(node, source)

        return FunctionSignature(
            name=name,
            parameters=params,
            return_type=return_type,
            is_async=is_async,
            docstring=docstring,
        )

    def _extract_parameters(self, params_node: Node, source: str) -> list[ParameterInfo]:
        """Extract parameters from a parameters node."""
        params = []

        for child in params_node.children:
            if child.type in ("identifier", "typed_parameter", "default_parameter",
                              "typed_default_parameter"):
                param = self._extract_single_parameter(child, source)
                if param and param.name not in ("self", "cls"):
                    params.append(param)

        return params

    def _extract_single_parameter(self, node: Node, source: str) -> Optional[ParameterInfo]:
        """Extract a single parameter."""
        if node.type == "identifier":
            return ParameterInfo(name=self.get_node_text(node, source))

        elif node.type == "typed_parameter":
            name_node = self.find_child(node, "identifier")
            type_node = self.find_child(node, "type")
            return ParameterInfo(
                name=self.get_node_text(name_node, source) if name_node else "",
                type_annotation=self.get_node_text(type_node, source) if type_node else None,
            )

        elif node.type == "default_parameter":
            name_node = self.find_child(node, "identifier")
            # Find default value (last child that's not the name)
            default = None
            for child in reversed(node.children):
                if child.type != "identifier" and child.type != "=":
                    default = self.get_node_text(child, source)
                    break
            return ParameterInfo(
                name=self.get_node_text(name_node, source) if name_node else "",
                default_value=default,
                is_optional=True,
            )

        elif node.type == "typed_default_parameter":
            name_node = self.find_child(node, "identifier")
            type_node = self.find_child(node, "type")
            # Find default value
            default = None
            for child in reversed(node.children):
                if child.type not in ("identifier", "type", "=", ":"):
                    default = self.get_node_text(child, source)
                    break
            return ParameterInfo(
                name=self.get_node_text(name_node, source) if name_node else "",
                type_annotation=self.get_node_text(type_node, source) if type_node else None,
                default_value=default,
                is_optional=True,
            )

        return None

    def _extract_decorators(self, node: Node, source: str) -> list[str]:
        """Extract decorator names from a decorated_definition."""
        decorators = []
        for child in node.children:
            if child.type == "decorator":
                # Get the decorator name (without @)
                for deco_child in child.children:
                    if deco_child.type in ("identifier", "attribute", "call"):
                        text = self.get_node_text(deco_child, source)
                        # For calls, just get the name part
                        if "(" in text:
                            text = text.split("(")[0]
                        decorators.append(text)
                        break
        return decorators

    def _extract_triggers(self, node: Node, source: str) -> list[TriggerInfo]:
        """
        Extract HTTP route or CLI command triggers from decorators.

        Supports:
        - FastAPI: @app.get("/path"), @router.post("/path")
        - Flask: @app.route("/path", methods=["GET"]), @bp.route(...)
        - Click: @click.command(), @app.cli.command()
        - Typer: @app.command()
        """
        triggers = []

        for child in node.children:
            if child.type != "decorator":
                continue

            # Get the full decorator text for analysis
            deco_text = self.get_node_text(child, source)

            # Find the call node to extract arguments
            call_node = self.find_child(child, "call")
            if not call_node:
                continue

            # Get the function being called (e.g., "app.get", "router.post")
            func_node = self.find_child(call_node, "attribute")
            if not func_node:
                func_node = self.find_child(call_node, "identifier")
            if not func_node:
                continue

            func_text = self.get_node_text(func_node, source)

            # Extract arguments
            args_node = self.find_child(call_node, "argument_list")
            route = None
            methods = []

            if args_node:
                # First positional argument is usually the route
                for arg in args_node.children:
                    if arg.type == "string":
                        route = self.get_node_text(arg, source).strip("'\"")
                        break
                    elif arg.type == "keyword_argument":
                        # Look for methods=["GET", "POST"]
                        key = self.find_child(arg, "identifier")
                        if key and self.get_node_text(key, source) == "methods":
                            list_node = self.find_child(arg, "list")
                            if list_node:
                                for item in list_node.children:
                                    if item.type == "string":
                                        methods.append(self.get_node_text(item, source).strip("'\""))

            # Detect HTTP triggers
            http_methods = {"get", "post", "put", "delete", "patch", "head", "options"}
            func_lower = func_text.lower()

            # FastAPI style: @app.get("/path"), @router.post("/path")
            for method in http_methods:
                if func_lower.endswith(f".{method}"):
                    triggers.append(TriggerInfo(
                        trigger_type="http",
                        method=method.upper(),
                        route=route or "/",
                    ))
                    break

            # Flask style: @app.route("/path", methods=["GET"])
            if ".route" in func_lower or func_lower == "route":
                if methods:
                    for method in methods:
                        triggers.append(TriggerInfo(
                            trigger_type="http",
                            method=method.upper(),
                            route=route or "/",
                        ))
                elif route:
                    # Default to GET if no methods specified
                    triggers.append(TriggerInfo(
                        trigger_type="http",
                        method="GET",
                        route=route,
                    ))

            # Click/Typer CLI triggers
            if "click.command" in func_lower or "typer.command" in func_lower or ".command" in func_lower:
                # Extract command name from decorator arg or use function name
                cmd_name = route  # Click uses first arg as command name sometimes
                triggers.append(TriggerInfo(
                    trigger_type="cli",
                    command=cmd_name,
                ))

        return triggers

    def _extract_docstring(self, node: Node, source: str) -> Optional[str]:
        """Extract docstring from a function or class."""
        body = self.find_child(node, "block")
        if not body or not body.children:
            return None

        first_stmt = None
        for child in body.children:
            if child.type == "expression_statement":
                first_stmt = child
                break

        if not first_stmt:
            return None

        string_node = self.find_child(first_stmt, "string")
        if string_node:
            text = self.get_node_text(string_node, source)
            # Remove quotes
            if text.startswith('"""') or text.startswith("'''"):
                return text[3:-3].strip()
            elif text.startswith('"') or text.startswith("'"):
                return text[1:-1].strip()

        return None

    def _try_extract_data_contract(self, node: Node, source: str) -> Optional[DataContractInfo]:
        """Try to extract a data contract from a class node."""
        class_node = node
        decorators = []

        if node.type == "decorated_definition":
            class_node = self.find_child(node, "class_definition")
            decorators = self._extract_decorators(node, source)
            if not class_node:
                return None

        name_node = self.find_child(class_node, "identifier")
        if not name_node:
            return None

        name = self.get_node_text(name_node, source)

        # Check for dataclass
        is_dataclass = "dataclass" in decorators or "dataclasses.dataclass" in decorators

        # Check for Pydantic BaseModel
        bases = []
        arg_list = self.find_child(class_node, "argument_list")
        if arg_list:
            for child in arg_list.children:
                if child.type in ("identifier", "attribute"):
                    bases.append(self.get_node_text(child, source))

        is_pydantic = "BaseModel" in bases or "pydantic.BaseModel" in bases

        # Check for TypedDict
        is_typed_dict = "TypedDict" in bases or "typing.TypedDict" in bases

        if not (is_dataclass or is_pydantic or is_typed_dict):
            return None

        # Determine contract type
        if is_dataclass:
            contract_type = "dataclass"
        elif is_pydantic:
            contract_type = "model"
        else:
            contract_type = "typeddict"

        # Extract fields
        fields = self._extract_class_fields(class_node, source)

        # Get source text
        source_text = self.get_node_text(node, source)

        return DataContractInfo(
            name=name,
            contract_type=contract_type,
            fields=fields,
            source_text=source_text,
        )

    def _extract_class_fields(self, class_node: Node, source: str) -> list[FieldInfo]:
        """Extract typed fields from a class body."""
        fields = []
        body = self.find_child(class_node, "block")
        if not body:
            return fields

        for child in body.children:
            if child.type == "expression_statement":
                # Look for type annotations: name: type or name: type = default
                inner = child.children[0] if child.children else None
                if inner and inner.type == "assignment":
                    # name: type = value
                    left = inner.children[0] if inner.children else None
                    if left and left.type == "identifier":
                        name = self.get_node_text(left, source)
                        type_node = self.find_child(inner, "type")
                        type_ann = self.get_node_text(type_node, source) if type_node else "Any"

                        # Check for Optional
                        is_optional = "Optional" in type_ann or type_ann.endswith("| None")

                        # Get default
                        default = None
                        for c in reversed(inner.children):
                            if c.type not in ("identifier", "type", "=", ":"):
                                default = self.get_node_text(c, source)
                                break

                        fields.append(FieldInfo(
                            name=name,
                            type_annotation=type_ann,
                            optional=is_optional or default is not None,
                            default_value=default,
                        ))

                elif inner and inner.type == "type":
                    # Just annotation without assignment: name: type
                    # The identifier should be before the :
                    pass  # This is more complex, skip for now

        return fields


# Register the extractor
register_extractor(PythonExtractor())
