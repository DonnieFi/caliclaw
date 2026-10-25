"""Checked CAD revision construction with protected named dimensions."""
import math
import re

from .fit import list_fit, protected_names
from .parts import save_part
from .repository import get_revision
from .revisions import validate_protected_dimensions
from .worker import build_model


def build_revision(db_path, project_id, parent_id, source, dimensions):
    if not isinstance(source, str) or not isinstance(dimensions, dict) or not dimensions:
        raise ValueError('Supply CAD body and named numeric dimensions.')
    for name, value in dimensions.items():
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', name):
            raise ValueError('Dimension names must be identifiers.')
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError('Dimensions must be finite numbers.')
        if re.search(r'\b' + re.escape(name) + r'\s*=', source):
            raise ValueError(f'Dimension {name} is supplied separately; do not assign it in the CAD body.')
    if parent_id:
        parent = get_revision(db_path, parent_id)
        if not parent or parent.project_id != project_id:
            raise ValueError('Current revision is unavailable.')
        previous = parent.params.get('dimensions', {})
        if not previous:
            raise ValueError('This part has no named CAD dimensions. Imported meshes are not recovered CAD; use Design for a new model.')
        protected = protected_names(list_fit(db_path, project_id))
        violations = validate_protected_dimensions(previous, dimensions, protected)
        if violations:
            raise ValueError('; '.join(violations))
    full_source = '\n'.join(f'{name} = {value};' for name, value in dimensions.items()) + '\n' + source
    result = build_model(full_source)
    if not result.ok or not result.stl_path:
        return result, None, None
    revision, artifact = save_part(db_path, project_id, parent_id, result.stl_path,
                                  params={'source': 'cad', 'dimensions': dimensions, 'scad': source},
                                  validation=result.mesh or {}, source=full_source)
    return result, revision, artifact
