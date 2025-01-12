# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import logging

from django.conf import settings
from django.contrib import auth
from django.http import HttpResponse
from django.template import RequestContext
from django.utils import six
from django.utils.http import is_safe_url
from django.views.decorators.cache import never_cache
from django.views.generic import View

from django_browserid.base import BrowserIDException, sanity_checks
from django_browserid.http import JSONResponse


logger = logging.getLogger(__name__)


class JSONView(View):
    def http_method_not_allowed(self, *args, **kwargs):
        response = JSONResponse({'error': 'Method not allowed.'}, status=405)
        allowed_methods = [m.upper() for m in self.http_method_names if hasattr(self, m)]
        response['Allow'] = ', '.join(allowed_methods)
        return response


def _get_next(request):
    """
    Get the next parameter from the request's POST arguments and
    validate it.

    :returns:
        The next parameter or None if it was not found or invalid.
    """
    next = request.POST.get('next')
    if is_safe_url(next, host=request.get_host()):
        return next
    else:
        return None


class Verify(JSONView):
    """
    Send an assertion to the remote verification service, and log the
    user in upon success.
    """
    @property
    def failure_url(self):
        """
        URL to redirect users to when login fails. This uses the value
        of ``settings.LOGIN_REDIRECT_URL_FAILURE``, and defaults to
        ``'/'`` if the setting doesn't exist.
        """
        return getattr(settings, 'LOGIN_REDIRECT_URL_FAILURE', '/')

    @property
    def success_url(self):
        """
        URL to redirect users to when login succeeds. This uses the
        value of ``settings.LOGIN_REDIRECT_URL``, and defaults to
        ``'/'`` if the setting doesn't exist.
        """
        return getattr(settings, 'LOGIN_REDIRECT_URL', '/')

    def login_success(self):
        """Log the user into the site."""
        auth.login(self.request, self.user)

        return JSONResponse({
            'email': self.user.email,
            'redirect': _get_next(self.request) or self.success_url
        })

    def login_failure(self, error=None):
        """
        Redirect the user to a login-failed page. This method can be
        overridden to handle different exceptions (for example different
        http status code for BrowserIDException and/or django exceptions).
        By default a 403 is returned for any exception.

        :param error:
            If login failed due to an error raised during verification,
            this will be the Exception or BrowserIDException instance that
            was raised.
        """
        if error:
            logger.error(error)

        return JSONResponse({'redirect': self.failure_url}, status=403)

    def post(self, *args, **kwargs):
        """
        Send the given assertion to the remote verification service and,
        depending on the result, trigger login success or failure.
        """
        assertion = self.request.POST.get('assertion')
        if not assertion:
            return self.login_failure()

        try:
            self.user = auth.authenticate(request=self.request, assertion=assertion)
        except Exception as e:
            return self.login_failure(e)

        if self.user and self.user.is_active:
            return self.login_success()

        return self.login_failure()

    def dispatch(self, request, *args, **kwargs):
        """
        Run some sanity checks on the request prior to dispatching it.
        """
        sanity_checks(request)
        return super(Verify, self).dispatch(request, *args, **kwargs)


class CsrfToken(JSONView):
    """Fetch a CSRF token for the frontend JavaScript."""
    @never_cache
    def get(self, request):
        # Different CSRF libraries (namely session_csrf) store the CSRF
        # token in different places. The only way to retrieve the token
        # that works with both the built-in CSRF and session_csrf is to
        # pull it from the template context processors via
        # RequestContext.
        context = RequestContext(request)

        # csrf_token might be a lazy value that triggers side-effects,
        # so we need to force it to a string.
        csrf_token = six.text_type(context.get('csrf_token', ''))

        return HttpResponse(csrf_token)


class Logout(JSONView):
    @property
    def redirect_url(self):
        """
        URL to redirect users to post-login. Uses
        ``settings.LOGOUT_REDIRECT_URL`` and defaults to ``/`` if the
        setting isn't found.
        """
        return getattr(settings, 'LOGOUT_REDIRECT_URL', '/')

    def post(self, request):
        """Log the user out."""
        auth.logout(request)

        return JSONResponse({
            'redirect': _get_next(self.request) or self.redirect_url
        })
