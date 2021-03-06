from django.contrib.auth.models import User
from manage_event.models import Profile, Events, AbortMessage
from django import forms
from django.utils.translation import ugettext_lazy as _
from django.core.validators import validate_email
from datetimewidget.widgets import DateTimeWidget
import datetime
import re


class InvitationForm(forms.Form):
    """
    Invitation forms.
    """
    emails = forms.CharField(label='',
                             widget=forms.Textarea(attrs={
                                                    'class': "form-control",
                                                    'rows': 5,
                                                    'placeholder': "Only support Gmail & Lionmail"}))

    def __init__(self, user_obj=None, *args, **kwargs):
        self.user_obj = user_obj
        super(InvitationForm, self).__init__(*args, **kwargs)

    def clean(self):
        """
        Clean up information.
        :return:
        """
        cleaned_data = super(InvitationForm, self).clean()
        emails = re.compile(r'[^\w.\-+@_]+').split(cleaned_data.get('emails'))
        self_email = self.user_obj.email
        error_list = []
        for email in emails:
            validate_email(email)
            _, domain_part = email.rsplit('@', 1)
            if domain_part != 'gmail.com' and domain_part != 'columbia.edu':
                raise forms.ValidationError('Email address should be Gmail or LionMail !',
                                            code='address error',)
            if email == self_email:
                raise forms.ValidationError("Email address should not be your own email!",
                                            code='own email error',)
        return emails


class UserForm(forms.ModelForm):
    """
    User forms.
    """

    class Meta:
        model = User
        fields = ('first_name', 'last_name', 'email')


class ProfileForm(forms.ModelForm):
    """
    Profile forms.
    """

    class Meta:
        model = Profile
        fields = ('bio', 'location', 'birth_date')


class AbortForm(forms.ModelForm):
    """
    Abort message forms.
    """

    class Meta:
        model = AbortMessage
        fields = ('Abort_message',)

        widgets = {
            'Abort_message': forms.Textarea(attrs={'class': "form-control", 'rows': 5})
        }


class DeadlineForm(forms.ModelForm):
    """
    Create event forms.
    """
    class Meta:
        model = Events
        fields = ('deadline',)
        dateTimeOptions = {
            'format': 'yyyy-mm-dd hh:ii',
            'minuteStep': 30,
            'showMeridian': True
        }
        widgets = {
            'deadline': DateTimeWidget(attrs={'class': 'form-control',
                                              'placeholder': "yyyy-mm-dd hh:mm"},
                                       bootstrap_version=3, options=dateTimeOptions),
        }

    def clean(self):
        cleaned_data = super(DeadlineForm, self).clean()
        deadline = self.cleaned_data.get('deadline')
        time_range_start = self.instance.time_range_start
        if deadline:
            error_list = []
            if deadline <= datetime.datetime.now():
                error = forms.ValidationError(
                    _("%(value1)s should be later than %(value2)s!"),
                    code='deadline error',
                    params={'value1': 'deadline',
                            'value2': 'current time'})
                error_list.append(error)
            if time_range_start <= deadline:
                error = forms.ValidationError(
                    _("%(value1)s should be later than %(value2)s!"),
                    code='start error',
                    params={'value1': 'time range start',
                            'value2': 'deadline'})
                error_list.append(error)
            if error_list:
                raise forms.ValidationError(error_list)


class EventForm(forms.ModelForm):
    """
    Create event forms.
    """

    class Meta:
        model = Events
        fields = ('event_name', 'time_range_start', 'time_range_end', 'duration', 'deadline', 'info')
        dateTimeOptions = {
            'format': 'yyyy-mm-dd hh:ii',
            'minuteStep': 30,
            'showMeridian': True
        }

        DURATION = (
            ('30:00', '30 min'),
            ('1:00:00', '1 h'),
            ('1:30:00', '1.5 h'),
            ('2:00:00', '2 h'),
            ('2:30:00', '2.5 h'),
            ('3:00:00', '3 h'),
            ('3:30:00', '3.5 h'),
            ('4:00:00', '4 h'),
            ('4:30:00', '4.5 h'),
            ('5:00:00', '5 h'),
        )

        widgets = {
            'event_name': forms.TextInput(attrs={'class': "form-control"}),
            'time_range_start': DateTimeWidget(attrs={'placeholder': "yyyy-mm-dd hh:mm"},
                                               bootstrap_version=3, options=dateTimeOptions),
            'time_range_end': DateTimeWidget(attrs={'placeholder': "yyyy-mm-dd hh:mm"},
                                             bootstrap_version=3, options=dateTimeOptions),
            'duration': forms.Select(attrs={'class': "form-control",
                                            }, choices=DURATION),
            'deadline': DateTimeWidget(attrs={'placeholder': "yyyy-mm-dd hh:mm"},
                                       bootstrap_version=3, options=dateTimeOptions),
            'info': forms.Textarea(attrs={'class': "form-control",
                                          'placeholder': "Description of this event",
                                          'rows': 5})
        }
        help_texts = {
            'event_name': _('*No more than 300 characters.'),
            'info': _('Optional'),
        }

    def clean(self):
        """
        Clean up information.
        :return:
        """
        cleaned_data = super(EventForm, self).clean()
        time_range_start = cleaned_data.get('time_range_start')
        time_range_end = cleaned_data.get('time_range_end')
        duration = cleaned_data.get('duration')
        deadline = self.cleaned_data.get('deadline')

        if time_range_end and time_range_start and deadline:
            error_list = []
            time_range = time_range_end - time_range_start
            if time_range_end > time_range_start and duration > time_range:
                error = forms.ValidationError(
                    _("%(value1)s should be smaller than %(value2)s!"),
                    code='duration error',
                    params={'value1': 'Duration',
                            'value2': 'time range'})
                error_list.append(error)

            if time_range_end <= time_range_start:
                error = forms.ValidationError(
                    _("%(value1)s should be later than %(value2)s!"),
                    code='end error',
                    params={'value1': 'Time range end',
                            'value2': 'time range start'})
                error_list.append(error)

            if time_range_start <= deadline:
                error = forms.ValidationError(
                    _("%(value1)s should be later than %(value2)s!"),
                    code='start error',
                    params={'value1': 'Time range start',
                            'value2': 'deadline'})
                error_list.append(error)

            if deadline <= datetime.datetime.now():
                error = forms.ValidationError(
                    _("%(value1)s should be later than %(value2)s!"),
                    code='deadline error',
                    params={'value1': 'Deadline',
                            'value2': 'current time'})
                error_list.append(error)

            if time_range > datetime.timedelta(days=7):
                error = forms.ValidationError(
                    _("Time range should be no more than %(value)s days!"),
                    code='time range error',
                    params={'value': '7'})
                error_list.append(error)

            if error_list:
                raise forms.ValidationError(error_list)
