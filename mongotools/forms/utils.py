import os
import itertools

from django import forms
from django.core.validators import EMPTY_VALUES
from mongoengine.base import ValidationError

from fields import DocumentFormFieldGenerator

def generate_field(field):
    generator = DocumentFormFieldGenerator()
    return generator.generate(field)

def mongoengine_validate_wrapper(field, old_clean, new_validate):
    """
    A wrapper function to validate formdata against mongoengine-field
    validator and raise a proper django.forms ValidationError if there
    are any problems.
    """
    def inner_validate(value, *args, **kwargs):
        value = old_clean(value, *args, **kwargs)

        # see:
        # django.forms.field.Field.validate
        # mongoengine.base.BaseDocument.validate
        if value not in EMPTY_VALUES:
            try:
                new_validate(value)
            except ValidationError, e:
                raise forms.ValidationError(e)
        else:
            value = None

        return value
    return inner_validate

def _get_unique_filename(fs, name):
    file_root, file_ext = os.path.splitext(name)
    count = itertools.count(1)
    while fs.exists(filename=name):
        # file_ext includes the dot.
        name = os.path.join("%s_%s%s" % (file_root, count.next(), file_ext))
    return name

def save_file(proxy, file):
    filename = _get_unique_filename(proxy.fs, file.name)
    file.file.seek(0)
    
    proxy.replace(file, content_type=file.content_type, filename=filename)
    return proxy
