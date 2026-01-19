"""
TypeScript AST Extractor

Extracts structured metadata from TypeScript/JavaScript source files using tree-sitter.
Handles .ts, .tsx, .js, .jsx files.
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
)


class TypeScriptExtractor(LanguageExtractor):
    """Extracts metadata from TypeScript/JavaScript source files."""

    @property
    def language(self) -> str:
        return "typescript"

    def extract_imports(self, tree: Tree, source: str) -> list[ImportInfo]:
        """Extract import statements."""
        imports = []
        root = tree.root_node

        for node in self.walk_tree(root, "import_statement"):
            module = ""
            names = []
            alias = None
            is_type_only = False

            # Check for type-only import
            for child in node.children:
                if child.type == "type":
                    is_type_only = True
                    break

            # Get the module path from string node
            string_node = self.find_child(node, "string")
            if string_node:
                module = self._extract_string_content(string_node, source)

            # Get import clause
            import_clause = self.find_child(node, "import_clause")
            if import_clause:
                for child in import_clause.children:
                    if child.type == "identifier":
                        # Default import: import X from 'y'
                        names.append(self.get_node_text(child, source))
                    elif child.type == "named_imports":
                        # Named imports: import { a, b } from 'y'
                        names.extend(self._extract_named_imports(child, source))
                    elif child.type == "namespace_import":
                        # Namespace import: import * as x from 'y'
                        for ns_child in child.children:
                            if ns_child.type == "identifier":
                                alias = self.get_node_text(ns_child, source)
                                names.append("*")
                                break

            if module:
                imports.append(ImportInfo(
                    module=module,
                    names=names if names else [],
                    alias=alias,
                    is_external=self._is_external_module(module),
                ))

        return imports

    def _extract_named_imports(self, node: Node, source: str) -> list[str]:
        """Extract names from named_imports node."""
        names = []
        for child in node.children:
            if child.type == "import_specifier":
                # Could be 'name' or 'name as alias'
                name_node = self.find_child(child, "identifier")
                if name_node:
                    names.append(self.get_node_text(name_node, source))
        return names

    def _extract_string_content(self, node: Node, source: str) -> str:
        """Extract string content without quotes."""
        # Find string_fragment child
        for child in node.children:
            if child.type == "string_fragment":
                return self.get_node_text(child, source)
        # Fallback: strip quotes
        text = self.get_node_text(node, source)
        return text.strip("'\"")

    def _is_external_module(self, module: str) -> bool:
        """Check if module is external (not relative)."""
        return not module.startswith(".")

    def extract_exports(self, tree: Tree, source: str) -> list[str]:
        """Extract exported symbol names."""
        exports = []
        root = tree.root_node

        for node in self.walk_tree(root, "export_statement"):
            # Check for re-exports: export { x } from 'y' or export * from 'y'
            has_from = any(c.type == "from" for c in node.children)
            if has_from:
                continue  # Skip re-exports, those are barrel file indicators

            for child in node.children:
                if child.type == "interface_declaration":
                    name_node = self.find_child(child, "type_identifier")
                    if name_node:
                        exports.append(self.get_node_text(name_node, source))

                elif child.type == "type_alias_declaration":
                    name_node = self.find_child(child, "type_identifier")
                    if name_node:
                        exports.append(self.get_node_text(name_node, source))

                elif child.type == "class_declaration":
                    name_node = self.find_child(child, "type_identifier")
                    if name_node:
                        exports.append(self.get_node_text(name_node, source))

                elif child.type == "function_declaration":
                    name_node = self.find_child(child, "identifier")
                    if name_node:
                        exports.append(self.get_node_text(name_node, source))

                elif child.type == "lexical_declaration":
                    # export const x = ...
                    for decl in self.walk_tree(child, "variable_declarator"):
                        name_node = self.find_child(decl, "identifier")
                        if name_node:
                            exports.append(self.get_node_text(name_node, source))

                elif child.type == "enum_declaration":
                    name_node = self.find_child(child, "identifier")
                    if name_node:
                        exports.append(self.get_node_text(name_node, source))

                elif child.type == "identifier":
                    # export default X or export { x }
                    exports.append(self.get_node_text(child, source))

                elif child.type == "export_clause":
                    # export { a, b, c }
                    for spec in self.walk_tree(child, "export_specifier"):
                        name_node = self.find_child(spec, "identifier")
                        if name_node:
                            exports.append(self.get_node_text(name_node, source))

        return exports

    def extract_classes(self, tree: Tree, source: str) -> list[ClassInfo]:
        """Extract class definitions."""
        classes = []
        root = tree.root_node

        for node in self.walk_tree(root, "class_declaration"):
            class_info = self._extract_class(node, source)
            if class_info:
                classes.append(class_info)

        return classes

    def _extract_class(self, node: Node, source: str) -> Optional[ClassInfo]:
        """Extract info from a class_declaration node."""
        name_node = self.find_child(node, "type_identifier")
        if not name_node:
            return None

        name = self.get_node_text(name_node, source)
        bases = []
        methods = []
        decorators = []
        is_abstract = False

        # Check for abstract keyword
        for child in node.children:
            if child.type == "abstract":
                is_abstract = True

        # Get extends and implements from class_heritage
        class_heritage = self.find_child(node, "class_heritage")
        if class_heritage:
            # Get extends clause
            extends_clause = self.find_child(class_heritage, "extends_clause")
            if extends_clause:
                for child in extends_clause.children:
                    if child.type == "identifier" or child.type == "type_identifier":
                        bases.append(self.get_node_text(child, source))

            # Get implements clause
            implements_clause = self.find_child(class_heritage, "implements_clause")
            if implements_clause:
                for child in self.walk_tree(implements_clause, "type_identifier"):
                    bases.append(self.get_node_text(child, source))

        # Extract methods from class body
        class_body = self.find_child(node, "class_body")
        if class_body:
            for child in class_body.children:
                if child.type == "method_definition":
                    method = self._extract_method(child, source)
                    if method:
                        methods.append(method)
                elif child.type == "public_field_definition":
                    # Could be arrow function property
                    pass

        return ClassInfo(
            name=name,
            bases=bases,
            methods=methods,
            decorators=decorators,
            is_dataclass=False,
        )

    def _extract_method(self, node: Node, source: str) -> Optional[FunctionSignature]:
        """Extract method from method_definition node."""
        name_node = self.find_child(node, "property_identifier")
        if not name_node:
            return None

        name = self.get_node_text(name_node, source)
        parameters = []
        return_type = None
        is_async = False
        decorators = []

        # Check for async
        for child in node.children:
            if child.type == "async":
                is_async = True

        # Get parameters
        params_node = self.find_child(node, "formal_parameters")
        if params_node:
            parameters = self._extract_parameters(params_node, source)

        # Get return type
        type_annotation = self.find_child(node, "type_annotation")
        if type_annotation:
            return_type = self._extract_type_annotation(type_annotation, source)

        return FunctionSignature(
            name=name,
            parameters=parameters,
            return_type=return_type,
            is_async=is_async,
            is_method=True,
            decorators=decorators,
        )

    def extract_functions(self, tree: Tree, source: str) -> list[FunctionSignature]:
        """Extract top-level function definitions."""
        functions = []
        root = tree.root_node

        for node in root.children:
            if node.type == "function_declaration":
                func = self._extract_function(node, source)
                if func:
                    functions.append(func)
            elif node.type == "export_statement":
                # Exported function
                func_node = self.find_child(node, "function_declaration")
                if func_node:
                    func = self._extract_function(func_node, source)
                    if func:
                        functions.append(func)
                # Also check for arrow functions in lexical_declaration
                lex_node = self.find_child(node, "lexical_declaration")
                if lex_node:
                    for decl in self.walk_tree(lex_node, "variable_declarator"):
                        arrow = self.find_child(decl, "arrow_function")
                        if arrow:
                            name_node = self.find_child(decl, "identifier")
                            if name_node:
                                func = self._extract_arrow_function(
                                    arrow, self.get_node_text(name_node, source), source
                                )
                                if func:
                                    functions.append(func)

        return functions

    def _extract_function(self, node: Node, source: str) -> Optional[FunctionSignature]:
        """Extract function from function_declaration node."""
        name_node = self.find_child(node, "identifier")
        if not name_node:
            return None

        name = self.get_node_text(name_node, source)
        parameters = []
        return_type = None
        is_async = False
        decorators = []

        # Check for async
        for child in node.children:
            if child.type == "async":
                is_async = True

        # Get parameters
        params_node = self.find_child(node, "formal_parameters")
        if params_node:
            parameters = self._extract_parameters(params_node, source)

        # Get return type
        type_annotation = self.find_child(node, "type_annotation")
        if type_annotation:
            return_type = self._extract_type_annotation(type_annotation, source)

        return FunctionSignature(
            name=name,
            parameters=parameters,
            return_type=return_type,
            is_async=is_async,
            is_method=False,
            decorators=decorators,
        )

    def _extract_arrow_function(
        self, node: Node, name: str, source: str
    ) -> Optional[FunctionSignature]:
        """Extract arrow function."""
        parameters = []
        return_type = None
        is_async = False

        # Check for async
        for child in node.children:
            if child.type == "async":
                is_async = True

        # Get parameters
        params_node = self.find_child(node, "formal_parameters")
        if params_node:
            parameters = self._extract_parameters(params_node, source)

        # Get return type
        type_annotation = self.find_child(node, "type_annotation")
        if type_annotation:
            return_type = self._extract_type_annotation(type_annotation, source)

        return FunctionSignature(
            name=name,
            parameters=parameters,
            return_type=return_type,
            is_async=is_async,
            is_method=False,
            decorators=[],
        )

    def _extract_parameters(self, node: Node, source: str) -> list[ParameterInfo]:
        """Extract parameters from formal_parameters node."""
        params = []

        for child in node.children:
            if child.type in ("required_parameter", "optional_parameter"):
                name = None
                type_annotation = None
                is_optional = child.type == "optional_parameter"

                # Get parameter name
                for param_child in child.children:
                    if param_child.type == "identifier":
                        name = self.get_node_text(param_child, source)
                    elif param_child.type == "type_annotation":
                        type_annotation = self._extract_type_annotation(
                            param_child, source
                        )

                if name:
                    params.append(ParameterInfo(
                        name=name,
                        type_annotation=type_annotation,
                        is_optional=is_optional,
                    ))

        return params

    def _extract_type_annotation(self, node: Node, source: str) -> str:
        """Extract type from type_annotation node."""
        # Skip the colon, get the actual type
        for child in node.children:
            if child.type != ":":
                return self.get_node_text(child, source)
        return ""

    def extract_data_contracts(self, tree: Tree, source: str) -> list[DataContractInfo]:
        """Extract interfaces, type aliases, and enums."""
        contracts = []
        root = tree.root_node

        # Interfaces
        for node in self.walk_tree(root, "interface_declaration"):
            contract = self._extract_interface(node, source)
            if contract:
                contracts.append(contract)

        # Type aliases
        for node in self.walk_tree(root, "type_alias_declaration"):
            contract = self._extract_type_alias(node, source)
            if contract:
                contracts.append(contract)

        # Enums
        for node in self.walk_tree(root, "enum_declaration"):
            contract = self._extract_enum(node, source)
            if contract:
                contracts.append(contract)

        return contracts

    def _extract_interface(self, node: Node, source: str) -> Optional[DataContractInfo]:
        """Extract interface as data contract."""
        name_node = self.find_child(node, "type_identifier")
        if not name_node:
            return None

        name = self.get_node_text(name_node, source)
        fields = []

        # Get interface body
        body = self.find_child(node, "interface_body")
        if body:
            for child in body.children:
                if child.type == "property_signature":
                    field = self._extract_property_signature(child, source)
                    if field:
                        fields.append(field)
                elif child.type == "method_signature":
                    # Method signatures could also be captured
                    pass

        return DataContractInfo(
            name=name,
            contract_type="interface",
            fields=fields,
            source_text=self.get_node_text(node, source),
        )

    def _extract_property_signature(self, node: Node, source: str) -> Optional[FieldInfo]:
        """Extract property from property_signature node."""
        name = None
        type_annotation = None
        is_optional = False

        for child in node.children:
            if child.type == "property_identifier":
                name = self.get_node_text(child, source)
            elif child.type == "?":
                is_optional = True
            elif child.type == "type_annotation":
                type_annotation = self._extract_type_annotation(child, source)

        if name:
            return FieldInfo(
                name=name,
                type_annotation=type_annotation or "unknown",
                optional=is_optional,
            )
        return None

    def _extract_type_alias(self, node: Node, source: str) -> Optional[DataContractInfo]:
        """Extract type alias as data contract."""
        name_node = self.find_child(node, "type_identifier")
        if not name_node:
            return None

        name = self.get_node_text(name_node, source)

        return DataContractInfo(
            name=name,
            contract_type="type",
            fields=[],
            source_text=self.get_node_text(node, source),
        )

    def _extract_enum(self, node: Node, source: str) -> Optional[DataContractInfo]:
        """Extract enum as data contract."""
        name_node = self.find_child(node, "identifier")
        if not name_node:
            return None

        name = self.get_node_text(name_node, source)
        fields = []

        # Get enum body
        body = self.find_child(node, "enum_body")
        if body:
            for child in body.children:
                if child.type == "enum_assignment":
                    field_name_node = self.find_child(child, "property_identifier")
                    if field_name_node:
                        fields.append(FieldInfo(
                            name=self.get_node_text(field_name_node, source),
                            type_annotation="enum_member",
                        ))

        return DataContractInfo(
            name=name,
            contract_type="enum",
            fields=fields,
            source_text=self.get_node_text(node, source),
        )

    def detect_entry_point(self, tree: Tree, source: str, file_path: str) -> Optional[str]:
        """Detect if file is an entry point."""
        path = Path(file_path)
        name = path.name.lower()

        # Main/index files
        if name in ("index.ts", "index.js", "main.ts", "main.js", "app.ts", "app.js"):
            # Check if it has meaningful exports/code (not just re-exports)
            if not self.detect_barrel(tree, source, file_path):
                return "main"

        # Check for Express/Fastify routes
        root = tree.root_node
        route_patterns = ["app.get", "app.post", "app.put", "app.delete", "router.get", "router.post"]

        source_lower = source.lower()
        for pattern in route_patterns:
            if pattern in source_lower:
                return "api_route"

        # Check for Next.js/Remix route handlers
        if "export default function" in source or "export async function" in source:
            if any(x in name for x in ["page.", "route.", "[", "+"]):
                return "api_route"

        # CLI detection
        if "commander" in source_lower or "yargs" in source_lower or "meow" in source_lower:
            return "cli"

        return None

    def detect_barrel(self, tree: Tree, source: str, file_path: str) -> bool:
        """Detect if file is a barrel file (re-exports only)."""
        path = Path(file_path)
        name = path.name.lower()

        # Only index files can be barrels
        if name not in ("index.ts", "index.js", "index.tsx", "index.jsx"):
            return False

        root = tree.root_node
        has_re_exports = False
        has_own_code = False

        for node in root.children:
            if node.type == "export_statement":
                # Check if it's a re-export (has 'from')
                has_from = any(c.type == "from" for c in node.children)
                if has_from:
                    has_re_exports = True
                else:
                    # It's exporting its own declarations
                    has_own_code = True
            elif node.type in (
                "function_declaration",
                "class_declaration",
                "lexical_declaration",
                "variable_declaration",
            ):
                has_own_code = True
            elif node.type == "import_statement":
                # Imports are okay, don't count as own code
                pass
            elif node.type == "comment":
                pass

        # It's a barrel if it only has re-exports
        return has_re_exports and not has_own_code


# Register the extractor
register_extractor(TypeScriptExtractor())
