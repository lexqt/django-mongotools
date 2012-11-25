import os
import itertools
from functools import wraps

from mongoengine import ValidationError

from django import forms
from django.core.validators import EMPTY_VALUES
from django.core.files.uploadedfile import UploadedFile

from mongotools.forms.fields import DocumentFormFieldGenerator



def generate_field(field):
    generator = DocumentFormFieldGenerator()
    return generator.generate(field)

def wrap_formfield_clean(formfield, field):
    """
    Wraps ``formfield.clean`` method to validate form data against
    MongoEngine field validator and reraise `django.forms.ValidationError`.
    """

    orig_clean = formfield.__class__.clean

    @wraps(orig_clean)
    def do_clean(self, value, *args, **kwargs):
        value = orig_clean(self, value, *args, **kwargs)

        # see:
        # `django.forms.field.Field.validate`
        # `mongoengine.base.BaseDocument.validate`
        if value not in EMPTY_VALUES:
            try:
                field._validate(value)
            except ValidationError, e:
                raise forms.ValidationError(e)
        else:
            value = None
        return value

    formfield.clean = do_clean.__get__(formfield, formfield.__class__)

    orig_deepcopy = formfield.__deepcopy__
    def new_deep_copy(memo):
        result = orig_deepcopy(memo)
        result.clean = do_clean.__get__(result, result.__class__)
        return result
    formfield.__deepcopy__ = new_deep_copy

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

def save_file_field(value, instance, field_name):
    if value is False:
        instance[field_name].delete()
    elif isinstance(value, UploadedFile):
        save_file(instance[field_name], value)
