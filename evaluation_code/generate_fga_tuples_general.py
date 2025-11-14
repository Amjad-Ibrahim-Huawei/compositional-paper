import random
import yaml
from collections import OrderedDict
import argparse

def process_template(item, num):
    """
    Recursively processes the item, substituting '{num}' with the provided num.
    If the item is a string, it is formatted.
    If the item is a dict or list, the function is applied recursively.
    """
    if isinstance(item, str):
        return item.format(num=num)
    elif isinstance(item, dict):
        return {k: process_template(v, num) for k, v in item.items()}
    elif isinstance(item, list):
        return [process_template(elem, num) for elem in item]
    else:
        return item

def main():
    # Setup argument parser for command-line arguments.
    parser = argparse.ArgumentParser(
        description="Generate OpenFGA tuples from static and dynamic relation templates."
    )
    parser.add_argument(
        "--num",
        type=int,
        default=1000,
        help="Number of dynamic tuples to generate (default: 1000)"
    )
    parser.add_argument(
        "--templates",
        type=str,
        default="templates.yaml",
        help="Path to YAML configuration file with relation templates (default: templates.yaml)"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="openfga_test_data.yaml",
        help="Output file name (default: openfga_test_data.yaml)"
    )
    args = parser.parse_args()

    # Load the configuration file which should contain two keys:
    # 'static_templates' and 'dynamic_templates'
    with open(args.templates, "r") as file:
        config = yaml.safe_load(file)
    
    if not isinstance(config, dict):
        raise ValueError("Templates file must contain a YAML mapping (dictionary) at the top level.")

    static_templates = config.get("static_templates", [])
    dynamic_templates = config.get("dynamic_templates", [])

    # List to store generated tuples.
    tuples = []

     # Add the static templates (if any) as they are.
    for static_tpl in static_templates:
        tuples.append(static_tpl)

    # Then, generate dynamic tuples by randomly selecting a template from dynamic_templates.
    for i in range(1, args.num + 1):
        if dynamic_templates:
            template = random.choice(dynamic_templates)
            
            # Build subject using the subject_template (substitute {num} with i)
            subject = template.get(
                "subject_template",
                f"{template.get('subject_type', 'user')}:{template.get('subject_type', 'user')}{i}"
            )
            try:
                subject = subject.format(num=i)
            except Exception:
                pass

            # Build object using the object_template (substitute {num} with i)
            object_value = template.get(
                "object_template",
                f"{template.get('object_type', 'object')}:{template.get('object_type', 'object')}{i}"
            )
            try:
                object_value = object_value.format(num=i)
            except Exception:
                pass

        # Create an OrderedDict to maintain key order:
        # "user", "relation", "object", then "condition" (if exists)
        tuple_data = {
        "user": subject,
        "relation": template["relation"],
        "object": object_value
        }	        
        # If the template includes a condition, process it generically and add it last.
        if "condition" in template:
            tuple_data["condition"] = process_template(template["condition"], i)
        
        tuples.append(tuple_data)

    # Write the tuples list to a YAML file (preserving key order).
    with open(args.output, "w") as file:
        yaml.dump(tuples, file, default_flow_style=False, sort_keys=False)

    print(f"YAML file with {len(tuples)} tuples has been generated as '{args.output}'.")

if __name__ == "__main__":
    main()
