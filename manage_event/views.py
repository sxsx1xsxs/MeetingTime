import datetime
import json
import sys
import re
from django.views import generic
from django.utils import timezone
from .models import Profile
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.http import HttpResponse, HttpResponseRedirect
from django.urls import reverse
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth import logout
from django.db import transaction
from .forms import UserForm, ProfileForm, EventForm, InvitationForm, AbortForm, DeadlineForm
from .models import Events, TimeSlots, EventUser, AbortMessage, Invitation
from notifications.models import Notification
from notifications.signals import notify
from django.contrib import messages
from django.utils.translation import ugettext_lazy as _
from django.db.models import Q
from django.core.mail import send_mail
from django.conf import settings
from django.template.loader import render_to_string
import functools


@login_required
def index(request):
    """
    Basic index page after user log in.
    :param request:
    :return:
    """
    user = request.user
    notifications = user.notifications.read()

    return render(request, 'manage_event/index.html', {
        'notifications': notifications,
    })


@login_required
def notification_redirect(request, event_id, notification_id):
    """
    Used for make notification as read and redirect to corresponding pages.
    :param request:
    :param event_id:
    :param notification_id:
    :return:
    """
    event = get_object_or_404(Events, pk=event_id)
    notification = get_object_or_404(Notification, pk=notification_id)
    notification.mark_as_read()
    if notification.verb == 'aborted event' or notification.verb == 'decided final time on event':
        return HttpResponseRedirect(reverse('manage_event:show_decision_result', args=(event_id,)))
    elif notification.verb == 'modified event':
        return HttpResponseRedirect(reverse('manage_event:modify_timeslots', args=(event_id,)))
    else:
        obj = Invitation.objects.filter(event=event).filter(email=request.user.email).first()
        accept_invite_url = reverse('manage_event:accept_invitation', args=[obj.key])
        decline_invite_url = reverse('manage_event:decline_invitation', args=[obj.key])
        accept_invite_url = request.build_absolute_uri(accept_invite_url)
        decline_invite_url = request.build_absolute_uri(decline_invite_url)
        return render(request, 'manage_event/invite_confirm.html', {
            'event': event,
            'accept_invite_url': accept_invite_url,
            'decline_invite_url': decline_invite_url
        })


@login_required
def organize_index(request):
    """
    Organize index page.
    :param request:
    :return:
    """
    # print(request.user.email)
    organized_events = EventUser.objects.filter(user=request.user).filter(role="o")
    organized_events_id = []

    for organized_event in organized_events:
        organized_events_id.append(organized_event.event.id)

    event_wait_for_decision = Events.objects.filter(Q(id__in=organized_events_id),
                                                    Q(status='Available'),
                                                    Q(final_time_start__isnull=True),
                                                    Q(deadline__lte=datetime.datetime.now())).order_by('-create_time')
    event_on_going = Events.objects.filter(Q(id__in=organized_events_id),
                                           Q(status='Available'),
                                           Q(deadline__gte=datetime.datetime.now())).order_by('-create_time')
    event_history = Events.objects.filter(Q(id__in=organized_events_id),
                                          Q(final_time_start__isnull=False) | Q(status='Abort')).order_by('-create_time')
    # latest_event_list = Events.objects.order_by('-event_date')[:5]
    # output = ', '.join([q.event_name for q in latest_event_list])
    return render(request, 'manage_event/organize_index.html', {
        'event_wait_for_decision': event_wait_for_decision,
        'event_on_going': event_on_going,
        'event_history': event_history
    })


@login_required
def participate_index(request):
    """
    Participate index page.
    :param request:
    :return:
    """

    participate_events = EventUser.objects.filter(user=request.user)
    participate_events_id = []
    for participate_event in participate_events:
        participate_events_id.append(participate_event.event.id)

    to_do_events_id = []
    done_events_id = []
    for participate_event_id in participate_events_id:
        if TimeSlots.objects.filter(user=request.user).filter(event_id=participate_event_id).count() == 0:
            to_do_events_id.append(participate_event_id)
        else:
            done_events_id.append(participate_event_id)

    event_to_do = Events.objects.filter(Q(id__in=to_do_events_id),
                                        Q(status='Available'),
                                        Q(deadline__gte=datetime.datetime.now())).order_by('-create_time')
    event_done = Events.objects.filter(Q(id__in=done_events_id),
                                       Q(status='Available'),
                                       Q(deadline__gte=datetime.datetime.now())).order_by('-create_time')
    event_result = Events.objects.filter(Q(id__in=participate_events_id),
                                         Q(final_time_start__isnull=False) | Q(status='Abort')).order_by('-create_time')
    event_pending = Events.objects.filter(Q(id__in=participate_events_id),
                                          Q(status='Available'),
                                          Q(deadline__lte=datetime.datetime.now())).exclude(final_time_start__isnull=False).order_by('-create_time')
    # latest_event_list = Events.objects.order_by('-event_date')[:5]
    # output = ', '.join([q.event_name for q in latest_event_list])
    return render(request, 'manage_event/participate_index.html', {
        'event_to_do': event_to_do,
        'event_done': event_done,
        'event_result': event_result,
        'event_pending': event_pending,
    })


@login_required
def create_event(request):
    """
    Create event page.
    :param request:
    :return:
    """
    if request.method == 'POST':
        form = EventForm(request.POST)
        if form.is_valid():
            event_data = form.cleaned_data
            event = Events.objects.create(**event_data)
            event.save()

            # create corresponding EventUser tuple.
            eventuser_data = {'event': event,
                              'user': request.user,
                              'role': 'o'}
            eventuser = EventUser.objects.create(**eventuser_data)
            eventuser.save()
            return HttpResponseRedirect(reverse('manage_event:create_publish', args=(event.id,)))
    else:
        form = EventForm()
    return render(request, 'manage_event/create_event.html', {'form': form})


@login_required
#@permission_required(role='o')
def modify_event_deadline_detail(request, event_id):
    """
    Modify event deadline and overwrite the datebase.
    :param request:
    :return:
    """
    event = get_object_or_404(Events, pk=event_id)
    #if EventUser.objects.get(event=event, user=request.user).role == 'o':
    if request.method == 'POST':
        form = DeadlineForm(request.POST, instance = event)
        if form.is_valid():
            modified_deadline = form.cleaned_data.get('deadline')
            event.deadline = modified_deadline
            event.save()
            return HttpResponseRedirect(reverse('manage_event:modify_event_deadline_result', args=(event_id,)))
    else:
        form = DeadlineForm()
        contents = {'event': event,
                    'message': "Cautious: Every participants will be notified about the change of submisson deadline."}
#else:
        #contents = {'event': event, 'error_message': "Sorry, you didn't have the access to modify the deadline of this event."}
    return render(request, 'manage_event/modify_event_deadline_detail.html', {'form': form})


def modify_event_deadline_result(request, event_id):
    event = get_object_or_404(Events, pk=event_id)

    # send notifications to all the participants
    notify.send(sender=request.user,
                recipient=[eventuser.user for eventuser in EventUser.objects.filter(event=event)],
                verb='modified event',
                target=event,
                description=event.id,
                timestamp=datetime.datetime.now().replace(microsecond=0))
    context = {'event': event}
    return render(request, 'manage_event/modify_event_deadline_result.html', context)


def send_invitation(request, event, objs):
    current_site = request.get_host()
    inviter = request.user.first_name + ' ' + request.user.last_name
    event_name = event.event_name

    for obj in objs:
        accept_invite_url = reverse('manage_event:accept_invitation', args=(obj.key,))
        decline_invite_url = reverse('manage_event:decline_invitation', args=(obj.key,))
        accept_invite_url = request.build_absolute_uri(accept_invite_url)
        decline_invite_url = request.build_absolute_uri(decline_invite_url)

        context = {
            'site_name': current_site,
            'inviter': inviter,
            'event_name': event_name,
            'accept_invite_url': accept_invite_url,
            'decline_invite_url': decline_invite_url,
        }

        msg_html = render_to_string('invitations/email/email_invite_message.html', context)
        msg_plain = render_to_string('invitations/email/email_invite_message.txt', context)
        sub_plain = render_to_string('invitations/email/email_invite_subject.txt', context)

        send_mail(sub_plain,
                  msg_plain,
                  settings.EMAIL_HOST_USER,
                  [obj.email],
                  html_message=msg_html
                  )

    mail_list = [obj.email for obj in objs]
    recipient_list = []
    for email in mail_list:
        user = User.objects.filter(email=email).first()
        if user:
            recipient_list.append(user)
    notify.send(sender=request.user,
                recipient=recipient_list,
                verb='invite you to join event',
                target=event,
                description=event.id,
                timestamp=datetime.datetime.now().replace(microsecond=0))


def invitation_required(foo):
    """
    :param foo:
    :return: wrapper
    decorator for checking user's invitation status for the event
    """
    @functools.wraps(foo)
    def wrapper(request, key):
        invitation = get_object_or_404(Invitation, key=key)
        current_email = request.user.email
        if current_email != invitation.email:
            messages.warning(request, _('Sorry, you are not been invited for this event!'))
            return HttpResponseRedirect(reverse('manage_event:index'))
        if invitation.confirmed:
            messages.info(request, _('Sorry, you have already made a decision for this invitation!'))
            return HttpResponseRedirect(reverse('manage_event:index'))
        return foo(request, key)
    return wrapper


def permission_required(role='p'):
    """
    :param role:
    :return: wrapper
    decorator for checking user's permission for the event
    """
    def decorator(foo):
        @functools.wraps(foo)
        def wrapper(request, event_id):
            event = get_object_or_404(Events, pk=event_id)
            user_list = [entry.user for entry in EventUser.objects.filter(event=event)]
            if request.user not in user_list:
                messages.warning(request, _('Sorry, you have no permission to view this event!'))
                return HttpResponseRedirect(reverse('manage_event:index'))
            eventuser = EventUser.objects.get(event=event, user=request.user)
            if role == 'o':
                if eventuser.role != 'o':
                    messages.warning(request, _('Sorry, you are not the organizer of this event!'))
                    return HttpResponseRedirect(reverse('manage_event:index'))
            return foo(request, event_id)
        return wrapper
    return decorator


def event_required(foo):
    @functools.wraps(foo)
    def wrapper(request, event_id):
        event = get_object_or_404(Events, pk=event_id)
        if event.status == 'Abort':
            messages.warning(request, _('Sorry, this event has been aborted!'))
            return HttpResponseRedirect(reverse('manage_event:index'))
        if datetime.datetime.now() > event.deadline:
            messages.warning(request, _('Sorry, this event has passed the deadline!'))
            return HttpResponseRedirect(reverse('manage_event:index'))
        return foo(request, event_id)
    return wrapper


@login_required
@invitation_required
def accept_invitation(request, key):
    invitation = get_object_or_404(Invitation, key=key)
    event = invitation.event

    event_required(event)
    if event.status == 'Abort':
        messages.warning(request, _('Sorry, this event has been aborted!'))
        return

    EventUser.objects.get_or_create(user=request.user, event=event)
    invitation.confirmed = True
    invitation.save()
    return HttpResponseRedirect(reverse('manage_event:select_timeslots', args=(event.id,)))


@login_required
@invitation_required
def decline_invitation(request, key):
    invitation = get_object_or_404(Invitation, key=key)
    invitation.confirmed = True
    invitation.save()

    messages.info(request, _('You have declined the invitation for event ' + invitation.event.event_name))
    return render(request, 'invitations/decline/decline_invitation.html')


@login_required
@permission_required(role='o')
@event_required
def create_publish(request, event_id):
    """
    Publish create result.
    :param request:
    :param event_id:
    :return:
    """
    # first check whether this event exists.
    event = get_object_or_404(Events, pk=event_id)

    contacts = [email for email in Invitation.objects.filter(inviter=request.user).values_list('email', flat=True).distinct()]
    if request.method == 'POST':
        form = InvitationForm(request.user, request.POST)
        if form.is_valid():
            mail_list = form.cleaned_data
            objs = Invitation.create(event=event, mail_list=mail_list, inviter=request.user)
            send_invitation(request, event, objs)

            messages.success(request, _('Invite Success!'))
            return HttpResponseRedirect(reverse('manage_event:create_publish', args=(event_id,)))
    else:
        form = InvitationForm()
    return render(request, 'manage_event/create_publish.html', {'event_id': event_id, 'form': form, 'contacts': contacts})


@login_required
@permission_required(role='o')
def abort_event_detail(request, event_id):
    """
    Abort event page.
    :param request:
    :param event_id:
    :return:
    """
    event = get_object_or_404(Events, pk=event_id)

    if request.method == 'POST':
        form = AbortForm(request.POST)
        if form.is_valid():
            AbortMessage.objects.get_or_create(event=event, Abort_message=form.cleaned_data['Abort_message'])
            event.status = 'Abort'
            event.save()
        return HttpResponseRedirect(reverse('manage_event:abort_event_result', args=(event_id,)))
    else:
        form = AbortForm()
        contents = {'event': event,
                    'message': "Caution: Once the event is aborted, it cannot be undo. Every participants will be infomed with the abort message.)",
                    'form': form.as_p()}

    return render(request, 'manage_event/abort_event_detail.html', contents)


@login_required
@permission_required(role='o')
def abort_event_result(request, event_id):
    """
    Show result after aborting event.
    :param request:
    :param event_id:
    :return:
    """
    event = get_object_or_404(Events, pk=event_id)
    message = AbortMessage.objects.get(event=event).Abort_message
    # send notifications to all the participants
    notify.send(sender=request.user,
                recipient=[eventuser.user for eventuser in EventUser.objects.filter(event=event)],
                verb='aborted event',
                #action_object=AbortMessage.objects.get(event=event),
                target=event,
                description=event.id,
                timestamp=datetime.datetime.now().replace(microsecond=0))
    return render(request, 'manage_event/abort_event_result.html', {'event': event, 'message': message})


@login_required
@permission_required()
def pending(request, event_id):
    """
    Pending event information page.
    :param request:
    :param event_id:
    :return:
    """
    event = get_object_or_404(Events, pk=event_id)

    timeslots = TimeSlots.objects.filter(event=event).filter(user=request.user).order_by('id')
    show_timeslots = []
    for t in timeslots:
        show_timeslots.append(t.time_slot_start.strftime('%Y-%m-%d %H:%M:%S'))

    context = {'event': event, 'timeslots': show_timeslots}
    return render(request, 'manage_event/pending.html', context)


@login_required
@permission_required(role='o')
def on_going(request, event_id):
    """
    On going event information page.
    :param request:
    :param event_id:
    :return:
    """
    event = get_object_or_404(Events, pk=event_id)
    if request.method == 'POST':
        form = InvitationForm(data = request.POST,user_obj = request.user)
        if form.is_valid():
            mail_list = form.cleaned_data
            objs = Invitation.create(event=event, mail_list=mail_list, inviter=request.user)
            send_invitation(request, event, objs)

            messages.success(request, _('Invite Success!'))
            return HttpResponseRedirect(reverse('manage_event:on_going', args=(event_id,)))
    else:
        form = InvitationForm(user_obj = request.user)
    return render(request, 'manage_event/on_going.html', {'event': event, 'form': form})


def get_result(event_id):
    """
    Get result based on all the time slots users provided.
    :param event_id:
    :return: A dictionary of the (time slot, number of available person) pair.
    """
    event = get_object_or_404(Events, pk=event_id)
    timeslots = event.timeslots_set.all()

    result = {}
    for timeslot in timeslots:
        time_slot_start = timeslot.time_slot_start
        if not result.get(time_slot_start):
            result[time_slot_start] = 1
        else:
            result[time_slot_start] += 1

    return result


@login_required
@permission_required(role='o')
def make_decision_detail(request, event_id):
    """
    Make decision page.
    :param request:
    :param event_id:
    :return:
    """
    event = get_object_or_404(Events, pk=event_id)
    # make_decision.html will call make_decision_json for data
    return render(request, 'manage_event/make_decision.html', {'event': event})


@login_required
@permission_required(role='o')
def make_decision_results(request, event_id):
    """
    Show decision results.
    :param request:
    :param event_id:
    :return:
    """
    event = get_object_or_404(Events, pk=event_id)
    if event.status == 'Abort':
        message = AbortMessage.objects.get(event=event).Abort_message
        return render(request, 'manage_event/abort_event_result.html', {'event': event, 'message': message})
    else:
        if event.final_time_end > datetime.datetime.now():
            contents = {'event': event, 'can_abort': '1'}
        else:
            contents = {'event': event}
        return render(request, 'manage_event/make_decision_results.html', contents)


@login_required
@permission_required(role='o')
def make_decision_json(request, event_id):
    """
    Used for .js parsing json by ajax.
    :param request:
    :param event_id:
    :return:
    """
    event = get_object_or_404(Events, pk=event_id)
    result = get_result(event_id)
    # result = {datetime.datetime(2017, 10, 20, 23, 30):1}
    time_range_start = event.time_range_start
    time_range_end = event.time_range_end

    # Make json data according to contract
    result_data = {}
    time = time_range_start
    thirty_mins = datetime.timedelta(minutes=30)
    while time < time_range_end:
        if not result.get(time):
            result_data[time.strftime("%Y-%m-%d %H:%M:%S")] = '0'
        else:
            result_data[time.strftime("%Y-%m-%d %H:%M:%S")] = str(result[time])
        time += thirty_mins
    result_json = json.dumps(result_data)
    return HttpResponse(result_json, content_type='application/json')


@login_required
@permission_required(role='o')
def make_decision(request, event_id):
    """
    Make decision page.
    :param request:
    :param event_id:
    :return:
    """
    event = get_object_or_404(Events, pk=event_id)

    if request.method == 'POST':
        decision_json = json.loads(request.body.decode("utf-8"))
        for key in decision_json:
            if decision_json[key] == "Selected":
                event.final_time_start = datetime.datetime.strptime(key, "%Y-%m-%d %H:%M:%S")
                event.save()
                for key_1 in decision_json:
                    if decision_json[key_1] == "Selected":
                        event.final_time_end = datetime.datetime.strptime(key_1, "%Y-%m-%d %H:%M:%S") + datetime.timedelta(minutes=30)
                        event.save()

                # send notifications to all the participants
                notify.send(sender=request.user,
                            recipient=[eventuser.user for eventuser in EventUser.objects.filter(event=event)],
                            verb='decided final time on event',
                            target=event,
                            description=event.id,
                            timestamp=datetime.datetime.now().replace(microsecond=0))
                name = request.POST.get('name')
                dictionary = {'name': name}
                return HttpResponse(json.dumps(dictionary), content_type='application/json')

    name = request.POST.get('name')
    dictionary = {'name': name}

    return HttpResponse(json.dumps(dictionary), content_type='application/json')


@login_required
@permission_required(role='o')
def make_decision_render(request, event_id):
    """
    Response to make decision.
    :param request:
    :param event_id:
    :return:
    """
    event = get_object_or_404(Events, pk=event_id)
    if event.final_time_start and event.final_time_end:
        # Always return an HttpResponseRedirect after successfully dealing
        # with POST data. This prevents data from being posted twice if a
        # user hits the Back button.
        return HttpResponseRedirect(reverse('manage_event:make_decision_results', args=(event.id,)))
    else:
        return render(request, 'manage_event/make_decision.html', {
            'event': event,
            'error_message': "You didn't make a decision.",
        })


@login_required
@permission_required()
def show_decision_result(request, event_id):
    """
    Show decision result page.
    :param request:
    :param event_id:
    :return:
    """
    event = get_object_or_404(Events, pk=event_id)
    if event.status == 'Abort':
        message = AbortMessage.objects.get(event=event).Abort_message
        return render(request, 'manage_event/show_abort_event_result.html', {'event': event, 'message': message})
    else:
        return render(request, 'manage_event/show_decision_result.html', {'event': event})


@login_required
@transaction.atomic
def update_profile(request):
    """
    Update profile.
    :param request:
    :return:
    """
    if request.method == 'POST':
        user_form = UserForm(request.POST, instance=request.user)
        profile_form = ProfileForm(request.POST, instance=request.user.profile)
        if user_form.is_valid() and profile_form.is_valid():
            user_form.save()
            profile_form.save()
            return HttpResponseRedirect('/manage_event/')
        else:
            messages.error(request, _('Please correct the error below.'))
    else:
        user_form = UserForm(instance=request.user)
        profile_form = ProfileForm(instance=request.user.profile)
    return render(request, 'manage_event/profile.html', {
        'user_form': user_form,
        'profile_form': profile_form
    })


@login_required
def webLogout(request):
    """
    Logout page.
    :param request:
    :return:
    """
    logout(request)
    return HttpResponseRedirect('/')


@login_required
@event_required
def select_timeslots(request, event_id):
    """
    Select timeslots page.
    :param request:
    :param event_id:
    :return:
    """
    event = get_object_or_404(Events, pk=event_id)
    if EventUser.objects.filter(user=request.user).filter(event=event).count() == 0:
        EventUser.objects.update_or_create(event=event, user=request.user, role="p")
    return render(request, 'manage_event/select_timeslots.html', {'event': event})


@login_required
@event_required
def modify_timeslots(request, event_id):
    """
    Modify timeslots page.
    :param request:
    :param event_id:
    :return:
    """
    event = get_object_or_404(Events, pk=event_id)
    return render(request, 'manage_event/modify_timeslots.html', {'event': event})


@login_required
def read_timeslots(request, event_id):
    """
    Read timeslots from frontend.
    :param request:
    :param event_id:
    :return:
    """
    event = get_object_or_404(Events, pk=event_id)
    user = request.user
    if request.method == 'POST':
        json_data = json.loads(request.body)
    else:
        json_data = {}
    dict_data = json_data

    for key, value in dict_data.items():
        if value == "Selected":
            TimeSlots.objects.update_or_create(event=event,
                                               user=user,
                                               time_slot_start=key)
    return HttpResponseRedirect(reverse('manage_event:select_publish', args=(event.id,)))


@login_required
def initialize_timeslots(request, event_id):
    """
    Initialize timeslots.
    :param request:
    :param event_id:
    :return:
    """
    event = get_object_or_404(Events, pk=event_id)
    time_range_start = event.time_range_start
    time_range_end = event.time_range_end
    user_data = {}
    time = time_range_start
    thirty_mins = datetime.timedelta(minutes=30)

    while time < time_range_end:
        user_data[time.strftime("%Y-%m-%d %H:%M:%S")] = "Blank"
        time += thirty_mins
    dumps = json.dumps(user_data)
    return HttpResponse(dumps, content_type='application/json')


@login_required
def select_publish(request, event_id):
    """
    Prepare json for select publish.
    :param request:
    :param event_id:
    :return:
    """
    name = request.POST.get('name')
    dictionary = {'name': name}
    return HttpResponse(json.dumps(dictionary), content_type='application/json')


@login_required
@event_required
def select_publish_render(request, event_id):
    """
    Pulish selection of time slots.
    :param request:
    :param event_id:
    :return:
    """
    event = get_object_or_404(Events, pk=event_id)
    timeslots = TimeSlots.objects.filter(event=event).filter(user=request.user).order_by('id')
    show_timeslots = []
    for t in timeslots:
        show_timeslots.append(t.time_slot_start.strftime('%Y-%m-%d %H:%M:%S'))
    context = {'event': event, 'timeslots': show_timeslots}
    return render(request, 'manage_event/select_publish.html', context)


@login_required
@event_required
def modify_timeslots_read(request, event_id):
    """
    Read modified time slots.
    :param request:
    :param event_id:
    :return:
    """
    event = get_object_or_404(Events, pk=event_id)
    time_range_start = event.time_range_start
    time_range_end = event.time_range_end
    q1 = TimeSlots.objects.filter(event=event)
    user_timeslots = q1.filter(user=request.user)
    # Make json data according to contract
    user_data = {}
    time = time_range_start
    thirty_mins = datetime.timedelta(minutes=30)

    while time < time_range_end:
        if not user_timeslots.filter(time_slot_start=time):
            user_data[time.strftime("%Y-%m-%d %H:%M:%S")] = "Blank"

        else:
            user_data[time.strftime("%Y-%m-%d %H:%M:%S")] = "Selected"
        time += thirty_mins
    dumps = json.dumps(user_data)
    return HttpResponse(dumps, content_type='application/json')


@login_required
@event_required
def modify_timeslots_update(request, event_id):
    """
    Update modified timeslots.
    :param request:
    :param event_id:
    :return:
    """
    event = get_object_or_404(Events, pk=event_id)
    user = request.user
    q1 = TimeSlots.objects.filter(event=event)
    user_timeslots = q1.filter(user=user)
    user_timeslots.delete()

    if request.method == 'POST':
        json_data = json.loads(request.body)
        dict_data = json_data
    else:
        dict_data = {}

    for key, value in dict_data.items():
        if value == "Selected":
            TimeSlots.objects.update_or_create(event=event,
                                               user=user,
                                               time_slot_start=key)
    return HttpResponseRedirect(reverse('manage_event:select_publish', args=(event.id,)))
