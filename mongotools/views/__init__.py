#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
#  Copyright (C) 2011 Wilson Pinto Júnior <wilsonpjunior@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.


# This file is based in Django Class Views
# adapted for use of mongoengine

from django.views.generic.detail import SingleObjectMixin, BaseDetailView
from django.views.generic.edit import FormMixin, ProcessFormView, DeletionMixin
from django.core.exceptions import ImproperlyConfigured, ObjectDoesNotExist
from django.utils.encoding import smart_str
from django.views.generic.base import TemplateResponseMixin, View
from django.http import HttpResponseRedirect, Http404
from django.views.generic.list import MultipleObjectMixin, BaseListView
from django.shortcuts import render
from django.contrib import messages

class MongoSingleObjectMixin(SingleObjectMixin):
    """
    Provides the ability to retrieve a single object for further manipulation.
    """
    document = None

    def get_object(self, queryset=None):
        """
        Returns the object the view is displaying.

        By default this requires `self.queryset` and a `pk` or `slug` argument
        in the URLconf, but subclasses can override this to return any object.
        """
        if queryset is None:
            queryset = self.get_queryset()

        pk = self.kwargs.get(self.pk_url_kwarg, None)
        slug = self.kwargs.get(self.slug_url_kwarg, None)
        if pk is not None:
            queryset = queryset.filter(pk=pk)

        elif slug is not None:
            slug_field = self.get_slug_field()
            queryset = queryset.filter(**{slug_field: slug})

        else:
            raise AttributeError(u"Generic detail view %s must be called with "
                                 u"either an object pk or a slug."
                                 % self.__class__.__name__)

        try:
            obj = queryset.get()
        except queryset._document.DoesNotExist:
            raise Http404(u"No %(verbose_name)s found matching the query" %
                          {'verbose_name': queryset._document.__name__})
        return obj

    def get_queryset(self):
        """
        Get the queryset to look an object up against. May not be called if
        `get_object` is overridden.
        """
        if self.queryset is None:
            if self.document:
                return self.document.objects
            else:
                raise ImproperlyConfigured(u"%(cls)s is missing a queryset. Define "
                                           u"%(cls)s.document, %(cls)s.queryset, or override "
                                           u"%(cls)s.get_object()." % {
                                                'cls': self.__class__.__name__
                                        })
        return self.queryset.clone()

    def get_context_object_name(self, obj):
        """
        Get the name to use for the object.
        """
        if self.context_object_name:
            return self.context_object_name
        elif hasattr(obj, '_meta'):
            return smart_str(obj.__class__.__name__.lower())
        else:
            return None

        
class MongoMultipleObjectMixin(MultipleObjectMixin):

    document = None
    
    def get_queryset(self):
        """
        Get the list of items for this view. This must be an interable, and may
        be a queryset (in which qs-specific behavior will be enabled).
        """
        if self.queryset is not None:
            queryset = self.queryset
            if hasattr(queryset, 'clone'):
                queryset = queryset.clone()
        elif self.document is not None:
            queryset = self.document.objects
        else:
            raise ImproperlyConfigured(u"'%s' must define 'queryset' or 'document'"
                                       % self.__class__.__name__)
        return queryset

class MongoSingleObjectTemplateResponseMixin(TemplateResponseMixin):
    template_name_field = None
    template_name_suffix = 'detail'

    def get_template_names(self):
        """
        Return a list of template names to be used for the request. Must return
        a list. May not be called if get_template is overridden.
        """
        
        try:
            names = super(MongoSingleObjectTemplateResponseMixin,
                          self).get_template_names()
        except ImproperlyConfigured:
            # If template_name isn't specified, it's not a problem --
            # we just start with an empty list.
            names = []

        # If self.template_name_field is set, grab the value of the field
        # of that name from the object; this is the most specific template
        # name, if given.
        if self.object and self.template_name_field:
            name = getattr(self.object, self.template_name_field, None)
            if name:
                names.insert(0, name)

        if hasattr(self.object, '_meta'):
            names.append("%s/%s.html" % (
                self.object.__class__.__name__.lower(),
                self.template_name_suffix
            ))
        elif hasattr(self, 'document') and hasattr(self.document, '_meta'):
            names.append("%s/%s.html" % (
                self.document.__name__.lower(),
                self.template_name_suffix
            ))

        return names

class MongoFormMixin(FormMixin, MongoSingleObjectMixin):
    """
    A mixin that provides a way to show and handle a mongoform in a request.
    """

    def get_form_class(self):
        """
        Returns the form class to use in this view
        """
        if not self.form_class:
            raise NotImplemented(u"Please specify the form_class"
                                 u" argument or get_form_class method")
        return self.form_class

    def get_form_kwargs(self):
        """
        Returns the keyword arguments for instanciating the form.
        """
        kwargs = super(MongoFormMixin, self).get_form_kwargs()
        obj = self.object
        if obj is not None:
            obj = self.get_object()  # get copy for form processing
        kwargs.update({'instance': obj})
        return kwargs

    def get_success_url(self):
        if self.success_url:
            url = self.success_url % self.object.__dict__
        else:
            try:
                url = self.object.get_absolute_url()
            except AttributeError:
                raise ImproperlyConfigured(
                    "No URL to redirect to.  Either provide a url or define"
                    " a get_absolute_url method on the Document.")
        return url

    def form_valid(self, form):
        instance = form.save()
        if instance is None:
            # see `BaseDocumentForm.save`
            return super(MongoFormMixin, self).form_invalid(form)
        self.object = instance
        return super(MongoFormMixin, self).form_valid(form)

    def get_context_data(self, **kwargs):
        context = kwargs
        if self.object:
            context['object'] = self.object
            context_object_name = self.get_context_object_name(self.object)
            if context_object_name:
                context[context_object_name] = self.object
        return context
        
class BaseDetailView(MongoSingleObjectMixin, BaseDetailView, View):
    pass

class BaseCreateView(MongoFormMixin, ProcessFormView):
    """
    Base view for creating an new object instance.

    Using this base class requires subclassing to provide a response mixin.
    """
    def get(self, request, *args, **kwargs):
        self.object = None
        return super(BaseCreateView, self).get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        self.object = None
        return super(BaseCreateView, self).post(request, *args, **kwargs)


class CreateView(MongoSingleObjectTemplateResponseMixin, BaseCreateView):
    """
    View for creating an new object instance,
    with a response rendered by template.
    """
    template_name_suffix = 'form'

class BaseUpdateView(MongoFormMixin, ProcessFormView):
    """
    Base view for updating an existing object.

    Using this base class requires subclassing to provide a response mixin.
    """
    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        return super(BaseUpdateView, self).get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        return super(BaseUpdateView, self).post(request, *args, **kwargs)


class UpdateView(MongoSingleObjectTemplateResponseMixin, BaseUpdateView):
    """
    View for updating an object,
    with a response rendered by template..
    """
    template_name_suffix = 'form'


class BaseDeleteView(DeletionMixin, BaseDetailView):
    """
    Base view for deleting an object.
    Using this base class requires subclassing to provide a response mixin.
    """

class DeleteView(MongoSingleObjectTemplateResponseMixin, BaseDeleteView):
    """
    View for deleting an object retrieved with `self.get_object()`,
    with a response rendered by template.
    """
    template_name_suffix = 'confirm_delete'
    
class BaseListView(MongoMultipleObjectMixin, BaseListView, View):
    pass

class MongoMultipleObjectTemplateResponseMixin(TemplateResponseMixin):
    template_name_suffix = 'list'

    def get_template_names(self):
        """
        Return a list of template names to be used for the request. Must return
        a list. May not be called if get_template is overridden.
        """
        try:
            names = super(MongoMultipleObjectTemplateResponseMixin, self).get_template_names()
        except ImproperlyConfigured:
            names = []

        if hasattr(self.object_list, '_document'):
            object_name = self.object_list._document.__name__
            names.append("%s/%s.html" % (object_name.lower(), self.template_name_suffix))

        return names

class DetailView(MongoSingleObjectTemplateResponseMixin, BaseDetailView):
    """
    Render a "detail" view of an object.

    By default this is a model instance looked up from `self.queryset`, but the
    view will support display of *any* object by overriding `self.get_object()`.
    """

class ListView(MongoMultipleObjectTemplateResponseMixin, BaseListView):
    """
    Render some list of objects, set by `self.model` or `self.queryset`.
    `self.queryset` can actually be any iterable of items, not just a queryset.
    """
