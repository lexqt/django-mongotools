from bson import ObjectId
from pymongo.errors import InvalidId

from mongoengine.fields import (ReferenceField as MongoReferenceField,
                                IntField, SequenceField)

from django import forms
from django.core.validators import EMPTY_VALUES
from django.utils.encoding import smart_unicode, force_unicode
from django.utils.text import capfirst
from django.utils.translation import ugettext_lazy as _

from mongotools.forms.widgets import ClearableGridFSFileInput



BLANK_CHOICE_DASH = [("", "---------")]

class MongoChoiceIterator(object):
    '''See `django.forms.models.ModelChoiceIterator`.'''

    def __init__(self, field):
        self.field = field
        self.queryset = field.queryset

    def __iter__(self):
        if self.field.empty_label is not None:
            yield (u"", self.field.empty_label)
        if self.field.cache_choices:
            if self.field.choice_cache is None:
                self.field.choice_cache = [
                    self.choice(obj) for obj in self.queryset.all()
                ]
            for choice in self.field.choice_cache:
                yield choice
        else:
            for obj in self.queryset.all():
                yield self.choice(obj)

    def __len__(self):
        return len(self.queryset)

    def choice(self, obj):
        return (self.field.prepare_value(obj), self.field.label_from_instance(obj))


class MongoCharField(forms.CharField):
    def to_python(self, value):
        if value in EMPTY_VALUES:
            return None
        return smart_unicode(value)

class ReferenceField(forms.ChoiceField):
    """
    Reference field for Mongo forms. Inspired by
    `django.forms.models.ModelChoiceField`.
    """

    def __init__(self, queryset, empty_label=u"---------", cache_choices=False,
                 required=True, initial=None, *args, **kwargs):
        if required and (initial is not None):
            self.empty_label = None
        else:
            self.empty_label = empty_label
        self.cache_choices = cache_choices
        self.coerce = kwargs.pop('coerce', ObjectId)

        # Call Field instead of ChoiceField __init__() because we don't need
        # ChoiceField.__init__().
        super(forms.ChoiceField, self).__init__(required, initial=initial,
                                                *args, **kwargs)
        self.queryset = queryset
        self.choice_cache = None

    def __deepcopy__(self, memo):
        result = super(forms.ChoiceField, self).__deepcopy__(memo)
        result.queryset = result.queryset.clone()
        return result

    def _get_queryset(self):
        return self._queryset

    def _set_queryset(self, queryset):
        self._queryset = queryset
        self.widget.choices = self.choices

    queryset = property(_get_queryset, _set_queryset)

    def label_from_instance(self, obj):
        """
        This method is used to convert objects into strings; it's used to
        generate the labels for the choices presented by this object. Subclasses
        can override this method to customize the display of the choices.
        """
        return smart_unicode(obj)

    def _get_choices(self):
        return MongoChoiceIterator(self)

    choices = property(_get_choices, forms.ChoiceField._set_choices)
    
    def prepare_value(self, value):
        if hasattr(value, '_meta'):
            return value.pk
        return super(ReferenceField, self).prepare_value(value)

    def clean(self, value):
        if value in EMPTY_VALUES:
            if self.required:
                raise forms.ValidationError(self.error_messages['required'])
            return None

        try:
            value = self.coerce(value)
            value = super(ReferenceField, self).clean(value)

            queryset = self.queryset.clone()
            obj = queryset.get(pk=value)
        except (ValueError, TypeError, InvalidId,
                self.queryset._document.DoesNotExist):
            raise forms.ValidationError(self.error_messages['invalid_choice'] %
                                        {'value': value})
        self.run_validators(value)
        return obj

class DocumentMultipleChoiceField(ReferenceField):
    """A MultipleChoiceField whose choices are a model QuerySet."""
    widget = forms.SelectMultiple   
    hidden_widget = forms.MultipleHiddenInput
    default_error_messages = {
        'list': _(u'Enter a list of values.'),
        'invalid_choice': _(u'Select a valid choice. %s is not one of the'
                            u' available choices.'),
        'invalid_pk_value': _(u'"%s" is not a valid value for a primary key.')
    }

    def __init__(self, queryset, *args, **kwargs):
        super(DocumentMultipleChoiceField, self).__init__(queryset, empty_label=None, *args, **kwargs)  

    def clean(self, value):
        if self.required and not value:
            raise forms.ValidationError(self.error_messages['required'])
        elif not self.required and not value:
            return []
        if not isinstance(value, (list, tuple)):
            raise forms.ValidationError(self.error_messages['list'])
        key = 'pk'
        
        filter_ids = []
        for pk in value:
            try:
                oid = ObjectId(pk)
                filter_ids.append(oid)
            except InvalidId:
                raise forms.ValidationError(self.error_messages['invalid_pk_value'] % pk)
        qs = self.queryset.clone()
        qs = qs.filter(**{'%s__in' % key: filter_ids})
        pks = set([force_unicode(getattr(o, key)) for o in qs])
        for val in value:
            if force_unicode(val) not in pks:
                raise forms.ValidationError(self.error_messages['invalid_choice'] % val)
        # Since this overrides the inherited ReferenceField.clean
        # we run custom validators here
        self.run_validators(value)
        return list(qs)

    def prepare_value(self, value):
        if hasattr(value, '__iter__') and not hasattr(value, '_meta'):
            return [super(DocumentMultipleChoiceField, self).prepare_value(v) for v in value]
        return super(DocumentMultipleChoiceField, self).prepare_value(value)


class DocumentFormFieldGenerator(object):
    """This is singleton class generates Django form-fields for mongoengine-fields."""
    
    def generate(self, field, **kwargs):
        """Tries to lookup a matching formfield generator (lowercase 
        field-classname) and raises a NotImplementedError of no generator
        can be found.
        """
        if hasattr(self, 'generate_%s' % field.__class__.__name__.lower()):
            return getattr(self, 'generate_%s' % \
                field.__class__.__name__.lower())(field, **kwargs)
        else:
            for cls in field.__class__.__bases__:
                if hasattr(self, 'generate_%s' % cls.__name__.lower()):
                    return getattr(self, 'generate_%s' % \
                                       cls.__name__.lower())(field, **kwargs)

            raise NotImplementedError('%s is not supported by DocumentForm' % \
                                          field.__class__.__name__)
                
    def get_field_choices(self, field, include_blank=True,
                          blank_choice=BLANK_CHOICE_DASH):
        # TODO: mongoengine supports flat list, Django do not
        # should it be supported here?
        first_choice = include_blank and blank_choice or []
        return first_choice + list(field.choices)

    def string_field(self, value):
        if value in EMPTY_VALUES:
            return None
        return smart_unicode(value)

    def integer_field(self, value):
        if value in EMPTY_VALUES:
            return None
        return int(value)

    def boolean_field(self, value):
        if value in EMPTY_VALUES:
            return None
        return value.lower() == 'true'

    def get_field_label(self, field):
        if field.verbose_name:
            return capfirst(field.verbose_name)
        if field.name:
            return capfirst(field.name)

    def get_field_help_text(self, field):
        if field.help_text:
            return field.help_text

    def generate_stringfield(self, field, **kwargs):
        form_class = MongoCharField

        defaults = {'label': self.get_field_label(field),
                    'initial': field.default,
                    'required': field.required,
                    'help_text': self.get_field_help_text(field)}

        if field.max_length and not field.choices:
            defaults['max_length'] = field.max_length
            
        if field.max_length is None and not field.choices:
            defaults['widget'] = forms.Textarea

        if field.regex:
            form_class = forms.RegexField
            defaults['regex'] = field.regex
        elif field.choices:
            form_class = forms.TypedChoiceField
            include_blank = not field.required
            defaults['choices'] = self.get_field_choices(field,
                                                 include_blank=include_blank)
            defaults['coerce'] = self.string_field

            if not field.required:
                defaults['empty_value'] = None
                
        defaults.update(kwargs)
        return form_class(**defaults)

    def generate_emailfield(self, field, **kwargs):
        defaults = {
            'required': field.required,
            'min_length': field.min_length,
            'max_length': field.max_length,
            'initial': field.default,
            'label': self.get_field_label(field),
            'help_text': self.get_field_help_text(field)    
        }
        
        defaults.update(kwargs)
        return forms.EmailField(**defaults)

    def generate_urlfield(self, field, **kwargs):
        defaults = {
            'required': field.required,
            'min_length': field.min_length,
            'max_length': field.max_length,
            'initial': field.default,
            'label': self.get_field_label(field),
            'help_text':  self.get_field_help_text(field)
        }
        
        defaults.update(kwargs)
        return forms.URLField(**defaults)

    def generate_intfield(self, field, **kwargs):
        if field.choices:
            defaults = {
                'coerce': self.integer_field,
                'empty_value': None,
                'required': field.required,
                'initial': field.default,
                'label': self.get_field_label(field),
                'choices': self.get_field_choices(field),
                'help_text': self.get_field_help_text(field)        
            }
            
            defaults.update(kwargs)
            return forms.TypedChoiceField(**defaults)
        else:
            defaults = {
                'required': field.required,
                'min_value': field.min_value,
                'max_value': field.max_value,
                'initial': field.default,
                'label': self.get_field_label(field),
                'help_text': self.get_field_help_text(field)      
            }
            
            defaults.update(kwargs)
            return forms.IntegerField(**defaults)

    def generate_floatfield(self, field, **kwargs):

        form_class = forms.FloatField

        defaults = {'label': self.get_field_label(field),
                    'initial': field.default,
                    'required': field.required,
                    'min_value': field.min_value,
                    'max_value': field.max_value,
                    'help_text': self.get_field_help_text(field)}

        defaults.update(kwargs)
        return form_class(**defaults)

    def generate_decimalfield(self, field, **kwargs):
        form_class = forms.DecimalField
        defaults = {'label': self.get_field_label(field),
                    'initial': field.default,
                    'required': field.required,
                    'min_value': field.min_value,
                    'max_value': field.max_value,
                    'help_text': self.get_field_help_text(field)}

        defaults.update(kwargs)
        return form_class(**defaults)

    def generate_booleanfield(self, field, **kwargs):
        if field.choices:
            defaults = {
                'coerce': self.boolean_field,
                'empty_value': None,
                'required': field.required,
                'initial': field.default,
                'label': self.get_field_label(field),
                'choices': self.get_field_choices(field),
                'help_text': self.get_field_help_text(field)        
            }
            
            defaults.update(kwargs)
            return forms.TypedChoiceField(**defaults)
        else:
            defaults = {
                'required': field.required,
                'initial': field.default,
                'label': self.get_field_label(field),
                'help_text': self.get_field_help_text(field)     
                }
            
            defaults.update(kwargs)
            return forms.BooleanField(**defaults)

    def generate_datetimefield(self, field, **kwargs):
        defaults = {
            'required': field.required,
            'initial': field.default,
            'label': self.get_field_label(field),
        }
        
        defaults.update(kwargs)
        return forms.DateTimeField(**defaults)

    def generate_referencefield(self, field, **kwargs):
        defaults = {
            'label': self.get_field_label(field),
            'help_text': self.get_field_help_text(field),
            'required': field.required
        }
        
        defaults.update(kwargs)

        id_field_name = field.document_type._meta['id_field']
        id_field = field.document_type._fields[id_field_name]

        if isinstance(id_field, (SequenceField, IntField)):
            defaults['coerce'] = int

        return ReferenceField(field.document_type.objects, **defaults)

    def generate_listfield(self, field, **kwargs):
        if field.field.choices:
            defaults = {
                'choices': field.field.choices,
                'required': field.required,
                'label': self.get_field_label(field),
                'help_text': self.get_field_help_text(field),
                'widget': forms.CheckboxSelectMultiple     
            }
            
            defaults.update(kwargs)
            return forms.MultipleChoiceField(**defaults)
        elif isinstance(field.field, MongoReferenceField):
            defaults = {
                'label': self.get_field_label(field),
                'help_text': self.get_field_help_text(field),
                'required': field.required
            }
        
            defaults.update(kwargs)
            f = DocumentMultipleChoiceField(field.field.document_type.objects, **defaults)
            return f
        raise NotImplementedError('Unsupported ListField configuration')

    def generate_filefield(self, field, **kwargs):
        defaults = {
            'required': field.required,
            'label': self.get_field_label(field),
            'initial': field.default,
            'help_text': self.get_field_help_text(field),
            'widget': ClearableGridFSFileInput,
        }
        defaults.update(kwargs)
        return forms.FileField(**defaults)

    def generate_imagefield(self, field, **kwargs):
        defaults = {
            'required':field.required,
            'label':self.get_field_label(field),
            'initial': field.default,
            'help_text': self.get_field_help_text(field),
            'widget': ClearableGridFSFileInput,
        }
        defaults.update(kwargs)
        return forms.ImageField(**defaults)


