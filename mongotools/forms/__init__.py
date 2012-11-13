import mongoengine
from mongoengine.fields import (ReferenceField, EmbeddedDocumentField,
                                FileField)

from django.core.exceptions import FieldError, NON_FIELD_ERRORS
from django import forms
from django.forms.forms import get_declared_fields
from django.forms.util import ErrorList
from django.forms.widgets import media_property
from django.core.files.uploadedfile import UploadedFile
from django.utils.datastructures import SortedDict

from mongotools.forms.fields import DocumentFormFieldGenerator
from mongotools.forms.utils import mongoengine_validate_wrapper, save_file

__all__ = ('DocumentForm', 'EmbeddedDocumentForm')



def update_instance(form, instance, fields=None, exclude=None):
    """
    Updates and returns a document instance from the bound
    ``form``'s ``cleaned_data``, but does not save the instance
    to the database.
    """
    cleaned_data = form.cleaned_data
    file_field_list = []
    for field_name, f in instance._fields.items():
        if not field_name in cleaned_data:
            continue
        if fields is not None and field_name not in fields:
            continue
        if exclude and field_name in exclude:
            continue
        if isinstance(f, FileField):
            file_field_list.append(f)
        else:
            instance[field_name] = cleaned_data[field_name]

    # TODO: should anything done with files before saving form?

    return instance

def save_instance(form, instance, fields=None, exclude=None, commit=True):
    """
    Saves bound Form ``form``'s cleaned_data into document instance ``instance``.

    If commit=True, then the changes to ``instance`` will be saved to the
    database. Returns ``instance``.
    """
    if form.errors:
        raise ValueError("The `%s` could not be saved because the data didn't"
                         " validate." % (instance,))

    for field_name, f in instance._fields.items():
        if fields is not None and field_name not in fields:
            continue
        if exclude and field_name in exclude:
            continue
        if isinstance(f, FileField):
            io = form.cleaned_data.get(field_name)

            # FIXME: should it be saved/deleted only if commit is True?
            if io is False:
                instance[field_name].delete()
            elif isinstance(io, UploadedFile):
                save_file(instance[field_name], io)

            continue

    if commit:
        instance.save()
    return instance

def document_to_dict(instance, fields=None, exclude=None):
    """
    Returns a dict containing the data in ``instance`` suitable for passing as
    a Form's ``initial`` keyword argument.

    ``fields`` is an optional list of field names. If provided, only the named
    fields will be included in the returned dict.

    ``exclude`` is an optional list of field names. If provided, the named
    fields will be excluded from the returned dict, even if they are listed in
    the ``fields`` argument.
    """
    data = {}
    for field_name, f in instance._fields.items():
        if fields and not field_name in fields:
            continue
        if exclude and field_name in exclude:
            continue
        if isinstance(f, ReferenceField) and instance[field_name]:
            data[field_name] = unicode(instance[field_name].id)
        else:
            data[field_name] = instance[field_name]
    return data

def fields_for_document(document, fields=None, exclude=None, widgets=None, formfield_generator=None):
    """
    Returns a ``SortedDict`` containing form fields for the given document.

    ``fields`` is an optional list of field names. If provided, only the named
    fields will be included in the returned fields.

    ``exclude`` is an optional list of field names. If provided, the named
    fields will be excluded from the returned fields, even if they are listed
    in the ``fields`` argument.
    """
    # see django.forms.forms.fields_for_model
    field_list = []
    ignored = []
    if hasattr(document, '_meta'):
        id_field = document._meta.get('id_field')
        if id_field not in fields:
            if exclude:
                exclude += (id_field,)
            else:
                exclude = [id_field]
    doc_fields = document._fields
    for field_name, f in sorted(doc_fields.items(), key=lambda t: t[1].creation_counter):
        if fields is not None and not field_name in fields:
            continue
        if exclude and field_name in exclude:
            continue
        if widgets and field_name in widgets:
            kwargs = {'widget': widgets[field_name]}
        else:
            kwargs = {}

        if not hasattr(formfield_generator, 'generate'):
            raise TypeError('formfield_generator must be an object with "generate" method')
        else:
            formfield = formfield_generator.generate(f, **kwargs)

        if not isinstance(f, FileField):
            formfield.clean = mongoengine_validate_wrapper(
                f,
                formfield.clean, f._validate)

        if formfield:
            field_list.append((field_name, formfield))
        else:
            ignored.append(field_name)
    field_dict = SortedDict(field_list)
    if fields:
        field_dict = SortedDict(
            [(f, field_dict.get(f)) for f in fields
                if ((not exclude) or (exclude and f not in exclude)) and (f not in ignored)]
        )
    return field_dict



class DocumentFormOptions(object):
    def __init__(self, options=None):
        self.document = getattr(options, 'document', None)
        self.fields = getattr(options, 'fields', None)
        self.exclude = getattr(options, 'exclude', None)
        self.widgets = getattr(options, 'widgets', None)
        self.embedded_field = getattr(options, 'embedded_field_name', None)
        self.formfield_generator = getattr(options, 'formfield_generator', DocumentFormFieldGenerator())


class DocumentFormMetaClass(type):
    """Metaclass to create a new DocumentForm."""
    # see django.forms.forms.ModelFormMetaclass

    def __new__(cls, name, bases, attrs):
        try:
            parents = [b for b in bases if issubclass(b, DocumentForm) or
                                           issubclass(b, EmbeddedDocumentForm)]
        except NameError:
            # We are defining DocumentForm itself.
            parents = None
        new_class = super(DocumentFormMetaClass, cls).__new__(cls, name, bases,
                attrs)
        if not parents:
            return new_class

        if 'media' not in attrs:
            new_class.media = media_property(new_class)
        opts = new_class._meta = DocumentFormOptions(getattr(new_class, 'Meta', None))
        declared_fields = get_declared_fields(bases, attrs, False)
        if opts.document:
            # If a document is defined, extract form fields from it.
            fields = fields_for_document(opts.document, opts.fields,
                                      opts.exclude, opts.widgets, opts.formfield_generator)
            # make sure fields doesn't specify an invalid field
            none_document_fields = [k for k, v in fields.iteritems() if not v]
            missing_fields = set(none_document_fields) - \
                             set(declared_fields.keys())
            if missing_fields:
                message = 'Unknown field(s) (%s) specified for %s'
                message = message % (', '.join(missing_fields),
                                     opts.document.__name__)
                raise FieldError(message)
            # Override default document fields with any custom declared ones
            # (plus, include all the other declared fields).
            fields.update(declared_fields)
        else:
            fields = declared_fields
        new_class.declared_fields = declared_fields
        new_class.base_fields = fields
        return new_class


class BaseDocumentForm(forms.BaseForm):

    def __init__(self, data=None, files=None, auto_id='id_%s', prefix=None,
                 initial=None, error_class=ErrorList, label_suffix=':',
                 empty_permitted=False, instance=None):
        opts = self._meta
        if instance is None:
            if opts.document is None:
                raise ValueError('MongoForm has no document class specified.')
            # if we didn't get an instance, instantiate a new one
            self.instance = opts.document()
            object_data = {}
            self.instance._adding = True
        else:
            self.instance = instance
            self.instance._adding = False
            object_data = document_to_dict(instance, opts.fields, opts.exclude)
        # if initial was provided, it should override the values from instance
        if initial is not None:
            object_data.update(initial)

        super(BaseDocumentForm, self).__init__(data, files, auto_id, prefix, object_data,
                                        error_class, label_suffix, empty_permitted)

    def _update_errors(self, message_dict):
        # see `django.forms.models.BaseModelForm._update_errors`
        for k, v in message_dict.items():
            if k != NON_FIELD_ERRORS:
                self._errors.setdefault(k, self.error_class()).extend(v)
                # Remove the data from the cleaned_data dict since it was invalid
                if k in self.cleaned_data:
                    del self.cleaned_data[k]
        if NON_FIELD_ERRORS in message_dict:
            messages = message_dict[NON_FIELD_ERRORS]
            self._errors.setdefault(NON_FIELD_ERRORS, self.error_class()).extend(messages)

    def _post_clean(self):
        opts = self._meta
        # Update the document instance with self.cleaned_data.
        update_instance(self, self.instance, opts.fields, opts.exclude)

        if hasattr(self.instance, 'clean'):
            # Call the model instance's clean method (mongoengine 0.8+)
            try:
                self.instance.clean()
            except mongoengine.ValidationError, e:
                self._update_errors({NON_FIELD_ERRORS: [e.message]})

    def save(self, commit=True):
        """save the instance or create a new one.."""
        opts = self._meta
        return save_instance(self, self.instance, opts.fields, opts.exclude, commit)


class DocumentForm(BaseDocumentForm):
    __metaclass__ = DocumentFormMetaClass


class EmbeddedDocumentForm(BaseDocumentForm):
    __metaclass__ = DocumentFormMetaClass

    def __init__(self, parent_document, *args, **kwargs):
        super(EmbeddedDocumentForm, self).__init__(*args, **kwargs)
        self.parent_document = parent_document
        field_name = self._meta.embedded_field
        if field_name is not None and \
                not hasattr(self.parent_document, field_name):
            raise FieldError("Parent document must have field %s" % field_name)
        # TODO: list fields (append or save at index), dynamic document fields?
        self.single_ref = isinstance(self.parent_document._fields[field_name],
                                     EmbeddedDocumentField)

    def save(self, commit=True):
        if self.errors:
            raise ValueError("The %s could not be saved because the data didn't"
                         " validate." % self.instance.__class__.__name__)

        val = None
        if self.single_ref:
            val = self.instance
#        l = getattr(self.parent_document, self._meta.embedded_field)
#        l.append(self.instance)
        setattr(self.parent_document, self._meta.embedded_field, val)
        if commit:
            self.parent_document.save()

        return self.instance
