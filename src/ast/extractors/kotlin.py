"""
Kotlin AST Extractor

Extracts structured metadata from Kotlin source files using tree-sitter.
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


class KotlinExtractor(LanguageExtractor):
    """Extracts metadata from Kotlin source files."""

    @property
    def language(self) -> str:
        return "kotlin"

    def extract_imports(self, tree: Tree, source: str) -> list[ImportInfo]:
        """Extract import statements."""
        imports = []
        root = tree.root_node

        for node in self.walk_tree(root, "import"):
            # Skip the 'import' keyword node
            if node.type != "import" or not node.children:
                continue

            # Find qualified_identifier
            qual_id = self.find_child(node, "qualified_identifier")
            if qual_id:
                module = self.get_node_text(qual_id, source)

                # Determine if external (simple heuristic: starts with common packages)
                is_external = not module.startswith(".")
                if any(module.startswith(pkg) for pkg in ["kotlinx.", "kotlin.", "java.", "javax.", "android."]):
                    is_external = True
                elif "." in module:
                    # Could be internal, check if it looks like a project import
                    is_external = True  # Default to external for qualified names

                imports.append(ImportInfo(
                    module=module,
                    is_external=is_external,
                ))

        return imports

    def extract_exports(self, tree: Tree, source: str) -> list[str]:
        """
        Extract exported symbols.

        In Kotlin, everything is public by default unless marked private/internal.
        """
        exports = []
        root = tree.root_node

        for node in root.children:
            if node.type == "class_declaration":
                name = self._get_class_name(node, source)
                if name and not self._is_private(node):
                    exports.append(name)

            elif node.type == "function_declaration":
                name = self._get_function_name(node, source)
                if name and not self._is_private(node):
                    exports.append(name)

            elif node.type == "object_declaration":
                name_node = self.find_child(node, "identifier")
                if name_node and not self._is_private(node):
                    exports.append(self.get_node_text(name_node, source))

        return exports

    def _is_private(self, node: Node) -> bool:
        """Check if node has private visibility."""
        modifiers = self.find_child(node, "modifiers")
        if modifiers:
            for child in self.walk_tree(modifiers, "private"):
                return True
            for child in self.walk_tree(modifiers, "internal"):
                return True
        return False

    def _get_class_name(self, node: Node, source: str) -> Optional[str]:
        """Get class/interface name from declaration."""
        name_node = self.find_child(node, "identifier")
        if name_node:
            return self.get_node_text(name_node, source)
        return None

    def _get_function_name(self, node: Node, source: str) -> Optional[str]:
        """Get function name from declaration."""
        name_node = self.find_child(node, "identifier")
        if name_node:
            return self.get_node_text(name_node, source)
        return None

    def extract_classes(self, tree: Tree, source: str) -> list[ClassInfo]:
        """Extract class and interface definitions."""
        classes = []
        root = tree.root_node

        for node in self.walk_tree(root, "class_declaration"):
            class_info = self._extract_class(node, source)
            if class_info:
                classes.append(class_info)

        return classes

    def _extract_class(self, node: Node, source: str) -> Optional[ClassInfo]:
        """Extract info from a class_declaration node."""
        name = self._get_class_name(node, source)
        if not name:
            return None

        bases = []
        methods = []
        decorators = []
        is_dataclass = False
        is_interface = False

        # Check if interface
        for child in node.children:
            if child.type == "interface":
                is_interface = True
                break

        # Check modifiers
        modifiers = self.find_child(node, "modifiers")
        if modifiers:
            for child in modifiers.children:
                if child.type == "class_modifier":
                    mod_text = self.get_node_text(child, source)
                    if "data" in mod_text:
                        is_dataclass = True
                    decorators.append(mod_text)

        # Get delegation specifiers (extends/implements)
        delegation = self.find_child(node, "delegation_specifiers")
        if delegation:
            for specifier in delegation.children:
                if specifier.type == "delegation_specifier":
                    # Get the type being extended
                    user_type = self.find_child(specifier, "user_type")
                    if user_type:
                        base_name = self._extract_type_text(user_type, source)
                        if base_name:
                            bases.append(base_name)

        # Extract methods from class body
        class_body = self.find_child(node, "class_body")
        if class_body:
            for child in class_body.children:
                if child.type == "function_declaration":
                    method = self._extract_function(child, source, is_method=True)
                    if method:
                        methods.append(method)

        return ClassInfo(
            name=name,
            bases=bases,
            methods=methods,
            decorators=decorators,
            is_dataclass=is_dataclass,
        )

    def extract_functions(self, tree: Tree, source: str) -> list[FunctionSignature]:
        """Extract top-level function definitions."""
        functions = []
        root = tree.root_node

        for node in root.children:
            if node.type == "function_declaration":
                func = self._extract_function(node, source, is_method=False)
                if func:
                    # Extract Spring annotation triggers
                    triggers = self._extract_spring_triggers(node, source)
                    if triggers:
                        func.triggers = triggers
                    functions.append(func)

        # Also extract Ktor DSL routes
        ktor_triggers = self._extract_ktor_routes(root, source)
        if ktor_triggers and functions:
            functions[0].triggers.extend(ktor_triggers)

        return functions

    def _extract_function(
        self, node: Node, source: str, is_method: bool = False
    ) -> Optional[FunctionSignature]:
        """Extract function from function_declaration node."""
        name = self._get_function_name(node, source)
        if not name:
            return None

        parameters = []
        return_type = None
        is_async = False
        decorators = []

        # Check modifiers for suspend
        modifiers = self.find_child(node, "modifiers")
        if modifiers:
            for child in self.walk_tree(modifiers, "suspend"):
                is_async = True

        # Get parameters
        params_node = self.find_child(node, "function_value_parameters")
        if params_node:
            parameters = self._extract_parameters(params_node, source)

        # Get return type - look for type after ':'
        found_colon = False
        for child in node.children:
            if child.type == ":":
                found_colon = True
            elif found_colon and child.type in ("user_type", "nullable_type"):
                return_type = self._extract_type_text(child, source)
                break

        return FunctionSignature(
            name=name,
            parameters=parameters,
            return_type=return_type,
            is_async=is_async,
            is_method=is_method,
            decorators=decorators,
        )

    def _extract_parameters(self, node: Node, source: str) -> list[ParameterInfo]:
        """Extract parameters from function_value_parameters node."""
        params = []

        for child in node.children:
            if child.type == "parameter":
                name = None
                type_annotation = None

                # Get parameter name and type
                for param_child in child.children:
                    if param_child.type == "identifier":
                        name = self.get_node_text(param_child, source)
                    elif param_child.type in ("user_type", "nullable_type"):
                        type_annotation = self._extract_type_text(param_child, source)

                if name:
                    params.append(ParameterInfo(
                        name=name,
                        type_annotation=type_annotation,
                    ))

        return params

    def _extract_type_text(self, node: Node, source: str) -> str:
        """Extract type text from user_type or nullable_type node."""
        return self.get_node_text(node, source)

    def extract_data_contracts(self, tree: Tree, source: str) -> list[DataContractInfo]:
        """Extract data classes, interfaces, sealed classes, and enums."""
        contracts = []
        root = tree.root_node

        for node in self.walk_tree(root, "class_declaration"):
            contract = self._extract_data_contract(node, source)
            if contract:
                contracts.append(contract)

        return contracts

    def _extract_data_contract(self, node: Node, source: str) -> Optional[DataContractInfo]:
        """Extract data contract from class_declaration if applicable."""
        name = self._get_class_name(node, source)
        if not name:
            return None

        # Determine contract type
        contract_type = None
        is_interface = False
        is_data = False
        is_sealed = False
        is_enum = False

        for child in node.children:
            if child.type == "interface":
                is_interface = True
                contract_type = "interface"
            elif child.type == "enum":
                is_enum = True
                contract_type = "enum"

        modifiers = self.find_child(node, "modifiers")
        if modifiers:
            mod_text = self.get_node_text(modifiers, source)
            if "data" in mod_text:
                is_data = True
                contract_type = "dataclass"
            if "sealed" in mod_text:
                is_sealed = True
                contract_type = "sealed_class"

        # Only return if it's a data contract type
        if not contract_type:
            return None

        fields = []

        # For data classes, extract primary constructor parameters as fields
        if is_data:
            primary_ctor = self.find_child(node, "primary_constructor")
            if primary_ctor:
                class_params = self.find_child(primary_ctor, "class_parameters")
                if class_params:
                    for param in class_params.children:
                        if param.type == "class_parameter":
                            field = self._extract_class_parameter(param, source)
                            if field:
                                fields.append(field)

        # For interfaces, extract abstract properties/methods as fields
        elif is_interface:
            class_body = self.find_child(node, "class_body")
            if class_body:
                for child in class_body.children:
                    if child.type == "property_declaration":
                        field = self._extract_property_field(child, source)
                        if field:
                            fields.append(field)

        return DataContractInfo(
            name=name,
            contract_type=contract_type,
            fields=fields,
            source_text=self.get_node_text(node, source),
        )

    def _extract_class_parameter(self, node: Node, source: str) -> Optional[FieldInfo]:
        """Extract field from class_parameter node (data class constructor)."""
        name = None
        type_annotation = None
        is_optional = False
        found_val_var = False
        found_colon = False

        for child in node.children:
            if child.type in ("val", "var"):
                found_val_var = True
            elif child.type == "identifier" and found_val_var and not found_colon:
                # Only take the identifier right after val/var and before the colon
                name = self.get_node_text(child, source)
            elif child.type == ":":
                found_colon = True
            elif child.type == "user_type":
                type_annotation = self._extract_type_text(child, source)
            elif child.type == "nullable_type":
                type_annotation = self._extract_type_text(child, source)
                is_optional = True
            elif child.type == "=":
                is_optional = True  # Has default value

        if name:
            return FieldInfo(
                name=name,
                type_annotation=type_annotation or "Any",
                optional=is_optional,
            )
        return None

    def _extract_property_field(self, node: Node, source: str) -> Optional[FieldInfo]:
        """Extract field from property_declaration node."""
        name = None
        type_annotation = None

        for child in node.children:
            if child.type == "variable_declaration":
                for var_child in child.children:
                    if var_child.type == "identifier":
                        name = self.get_node_text(var_child, source)
            elif child.type in ("user_type", "nullable_type"):
                type_annotation = self._extract_type_text(child, source)

        if name:
            return FieldInfo(
                name=name,
                type_annotation=type_annotation or "Any",
            )
        return None

    def _extract_spring_triggers(self, node: Node, source: str) -> list[TriggerInfo]:
        """
        Extract Spring annotation triggers from a function declaration.

        Looks for patterns like:
        - @GetMapping("/path")
        - @PostMapping("/users")
        - @RequestMapping("/api", method = RequestMethod.GET)
        - @DeleteMapping
        """
        triggers = []

        # Spring mapping annotations to HTTP methods
        mapping_annotations = {
            "GetMapping": "GET",
            "PostMapping": "POST",
            "PutMapping": "PUT",
            "DeleteMapping": "DELETE",
            "PatchMapping": "PATCH",
            "RequestMapping": None,  # Method specified in annotation
        }

        # Look for annotations on the function
        modifiers = self.find_child(node, "modifiers")
        if not modifiers:
            return triggers

        for child in modifiers.children:
            if child.type == "annotation":
                # Get the annotation text
                ann_text = self.get_node_text(child, source)

                for ann_name, http_method in mapping_annotations.items():
                    if ann_name in ann_text:
                        # Extract route from annotation arguments
                        route = self._extract_annotation_route(ann_text)

                        # For RequestMapping, try to extract method
                        method = http_method
                        if ann_name == "RequestMapping":
                            if "GET" in ann_text.upper():
                                method = "GET"
                            elif "POST" in ann_text.upper():
                                method = "POST"
                            elif "PUT" in ann_text.upper():
                                method = "PUT"
                            elif "DELETE" in ann_text.upper():
                                method = "DELETE"
                            else:
                                method = "GET"  # Default

                        triggers.append(TriggerInfo(
                            trigger_type="http",
                            method=method,
                            route=route or "/",
                        ))
                        break

        return triggers

    def _extract_annotation_route(self, ann_text: str) -> Optional[str]:
        """Extract route path from annotation text like @GetMapping("/users")."""
        # Look for quoted string in annotation
        import re
        match = re.search(r'["\']([^"\']+)["\']', ann_text)
        if match:
            return match.group(1)
        return None

    def _extract_ktor_routes(self, root: Node, source: str) -> list[TriggerInfo]:
        """
        Extract Ktor DSL route definitions.

        Looks for patterns like:
        - get("/path") { ... }
        - post("/users") { ... }
        - route("/api") { get { ... } }
        - routing { get("/path") { ... } }
        """
        triggers = []
        http_methods = {"get", "post", "put", "delete", "patch", "head", "options"}

        for node in self.walk_tree(root, "call_expression"):
            # Get the function name being called
            func_node = self.find_child(node, "identifier")
            if not func_node:
                # Try simple_identifier
                func_node = self.find_child(node, "simple_identifier")
            if not func_node:
                continue

            func_name = self.get_node_text(func_node, source).lower()

            if func_name not in http_methods:
                continue

            # Extract route from arguments
            route = None
            call_suffix = self.find_child(node, "call_suffix")
            if call_suffix:
                value_args = self.find_child(call_suffix, "value_arguments")
                if value_args:
                    for arg in value_args.children:
                        if arg.type == "value_argument":
                            # Get string literal
                            for arg_child in self.walk_tree(arg, "string_literal"):
                                text = self.get_node_text(arg_child, source)
                                route = text.strip('"\'')
                                break
                        if route:
                            break

            triggers.append(TriggerInfo(
                trigger_type="http",
                method=func_name.upper(),
                route=route or "/",
            ))

        return triggers

    def detect_entry_point(self, tree: Tree, source: str, file_path: str) -> Optional[str]:
        """Detect if file is an entry point."""
        path = Path(file_path)
        name = path.name.lower()

        # Check for main function
        root = tree.root_node
        for node in root.children:
            if node.type == "function_declaration":
                func_name = self._get_function_name(node, source)
                if func_name == "main":
                    return "main"

        # Check for Android entry points
        if "activity" in name or "fragment" in name:
            # Check if extends Activity/Fragment
            for node in self.walk_tree(root, "class_declaration"):
                delegation = self.find_child(node, "delegation_specifiers")
                if delegation:
                    text = self.get_node_text(delegation, source).lower()
                    if "activity" in text or "fragment" in text:
                        return "android_component"

        # Check for Ktor/Spring routes
        if any(x in source.lower() for x in ["routing", "route(", "@getmapping", "@postmapping", "@controller"]):
            return "api_route"

        return None

    def detect_barrel(self, tree: Tree, source: str, file_path: str) -> bool:
        """
        Detect if file is a barrel file.

        Kotlin doesn't have barrel files in the same way as TypeScript/Python.
        Package-level functions in separate files serve a similar purpose.
        """
        return False  # Kotlin doesn't use barrel files


# Register the extractor
register_extractor(KotlinExtractor())
