# Python dependencies
import sys, json

# 3rd Party Dependencies
import requests,urllib
from bs4 import BeautifulSoup

# Custom Exception
class ResponseError(Exception):
	def __init__(self, message,response):
		super(Exception, self).__init__(message)
		self.response = response


class GoogleTrendsAPI(object):
    """
    Google Trends API
    """

    GET_METHOD = 'get'
    POST_METHOD = 'post'

    LOGIN_URL = 'https://accounts.google.com/ServiceLogin'
    AUTH_URL = 'https://accounts.google.com/ServiceLoginAuth'

    GENERAL_URL = 'https://www.google.com/trends/api/explore'
    INTEREST_OVER_TIME_URL = 'https://www.google.com/trends/api/widgetdata/multiline'
    INTEREST_BY_REGION_URL = 'https://www.google.com/trends/api/widgetdata/comparedgeo'
    RELATED_QUERIES_URL = 'https://www.google.com/trends/api/widgetdata/relatedsearches'
    TRENDING_SEARCHES_URL = 'https://trends.google.com/trends/hottrends/hotItems'
    TOP_CHARTS_URL = 'https://trends.google.com/trends/topcharts/chart'
    SUGGESTIONS_URL = 'https://www.google.com/trends/api/autocomplete/'

    def __init__(self, google_username, google_password, hl='en-US', tz=360, geo='US', custom_useragent='PyTrends',
                 proxies=None):
        """
        Initialize hard-coded URLs, HTTP headers, and login parameters
        needed to connect to Google Trends, then connect.
        """
        self.username = google_username
        self.password = google_password
        # google rate limit
        self.google_rl = 'You have reached your quota limit. Please try again later.'
        # custom user agent so users know what "new account signin for Google" is
        self.custom_useragent = {'User-Agent': custom_useragent}
        self._connect(proxies=proxies)
        self.results = None

        # set user defined options used globally
        self.tz = tz
        self.hl = hl
        self.geo = geo
        self.kw_list = list()

        # intialize widget payloads
        self.interest_over_time_widget = dict()
        self.interest_by_region_widget = dict()
        self.related_queries_widget_list = list()

    def _connect(self, proxies=None):
        """
        Connect to Google.
        Go to login page GALX hidden input value and send it back to google + login and password.
        http://stackoverflow.com/questions/6754709/logging-in-to-google-using-python
        """
        self.ses = requests.session()
        if proxies:
            self.ses.proxies.update(proxies)
        login_html = self.ses.get(GoogleTrendsAPI.LOGIN_URL, headers=self.custom_useragent)
        soup_login = BeautifulSoup(login_html.content, 'lxml').find('form').find_all('input')
        form_data = dict()
        for u in soup_login:
            if u.has_attr('value') and u.has_attr('name'):
                form_data[u['name']] = u['value']
        # override the inputs with out login and pwd:
        form_data['Email'] = self.username
        form_data['Passwd'] = self.password
        self.ses.post(GoogleTrendsAPI.AUTH_URL, data=form_data)

    def _get_data(self, url, method=GET_METHOD, trim_chars=0, **kwargs):
        """Send a request to Google and return the JSON response as a Python object
        :param url: the url to which the request will be sent
        :param method: the HTTP method ('get' or 'post')
        :param trim_chars: how many characters should be trimmed off the beginning of the content of the response
            before this is passed to the JSON parser
        :param kwargs: any extra key arguments passed to the request builder (usually query parameters or data)
        :return:
        """
        if method == GoogleTrendsAPI.POST_METHOD:
            response = self.ses.post(url, **kwargs)
        else:
            response = self.ses.get(url, **kwargs)

        # check if the response contains json and throw an exception otherwise
        # Google mostly sends 'application/json' in the Content-Type header,
        # but occasionally it sends 'application/javascript
        # and sometimes even 'text/javascript
        if 'application/json' in response.headers['Content-Type'] or \
                        'application/javascript' in response.headers['Content-Type'] or \
                                        'text/javascript' in response.headers['Content-Type']:

            # trim initial characters
            # some responses start with garbage characters, like ")]}',"
            # these have to be cleaned before being passed to the json parser
            content = response.text[trim_chars:]

            # parse json
            return json.loads(content)
        else:
            # this is often the case when the amount of keywords in the payload for the IP
            # is not allowed by Google
            raise ResponseError('The request failed: Google returned a response with code {0}.'.format(response.status_code), response=response)

    def build_payload(self, kw_list, cat=0, timeframe='today 12-m', geo='', gprop=''):
        """Create the payload for related queries, interest over time and interest by region"""
        self.kw_list = kw_list
        self.geo = geo
        token_payload = {
            'hl': self.hl,
            'tz': self.tz,
            'req': {'comparisonItem': [], 'category': cat},
            'property': gprop,
        }

        # build out json for each keyword
        for kw in self.kw_list:
            keyword_payload = {'keyword': kw, 'time': timeframe, 'geo': self.geo}
            token_payload['req']['comparisonItem'].append(keyword_payload)
        # requests will mangle this if it is not a string
        token_payload['req'] = json.dumps(token_payload['req'])
        # get tokens
        self._tokens(token_payload)
        return

    def _tokens(self, token_payload):
        """Makes request to Google to get API tokens for interest over time, interest by region and related queries"""

        # make the request and parse the returned json
        widget_dict = self._get_data(
            url=GoogleTrendsAPI.GENERAL_URL,
            method=GoogleTrendsAPI.GET_METHOD,
            params=token_payload,
            trim_chars=4,
        )['widgets']

        # order of the json matters...
        first_region_token = True
        # clear self.related_queries_widget_list of old keywords'widgets
        self.related_queries_widget_list = []
        # assign requests
        for widget in widget_dict:
            if widget['title'] == 'Interest over time':
                self.interest_over_time_widget = widget
            if widget['title'] == 'Interest by region' and first_region_token:
                self.interest_by_region_widget = widget
                first_region_token = False
            if widget['title'] == 'Interest by subregion' and first_region_token:
                self.interest_by_region_widget = widget
                first_region_token = False
            # response for each term, put into a list
            if widget['title'] == 'Related queries':
                self.related_queries_widget_list.append(widget)
        return

    def interest_over_time(self):
        """Request data from Google's Interest Over Time section and return a dataframe"""

        over_time_payload = {
            # convert to string as requests will mangle
            'req': json.dumps(self.interest_over_time_widget['request']),
            'token': self.interest_over_time_widget['token'],
            'tz': self.tz
        }

        # make the request and parse the returned json
        timelineData = self._get_data(
            url=GoogleTrendsAPI.INTEREST_OVER_TIME_URL,
            method=GoogleTrendsAPI.GET_METHOD,
            trim_chars=5,
            params=over_time_payload,
        )[u'default'][u'timelineData']

        #clean timelineData
        for d in timelineData:
        	del d[u'formattedValue']
        	d[u'time'] = int(d[u'time'])
        	d[u'value'] = int(d[u'value'][0])

        return timelineData


    def interest_by_region(self, resolution='COUNTRY'):
        """Request data from Google's Interest by Region section and return a dataframe"""

        # make the request
        region_payload = dict()
        if self.geo == '':
            self.interest_by_region_widget['request']['resolution'] = resolution
        # convert to string as requests will mangle
        region_payload['req'] = json.dumps(self.interest_by_region_widget['request'])
        region_payload['token'] = self.interest_by_region_widget['token']
        region_payload['tz'] = self.tz

        # parse returned json
        geoMapData = self._get_data(
            url=GoogleTrendsAPI.INTEREST_BY_REGION_URL,
            method=GoogleTrendsAPI.GET_METHOD,
            trim_chars=5,
            params=region_payload
        )[u'default'][u'geoMapData']

        # clean data
        for d in geoMapData:
        	del d[u'maxValueIndex']
        	del d[u'coordinates']
        	del d[u'formattedValue']
        	d[u'value'] = int(d[u'value'][0])

        return geoMapData


    def related_queries(self):
        """Request data from Google's Related Queries section and return a dictionary of dataframes
        If no top and/or rising related queries are found, the value for the key "top" and/or "rising" will be None
        """

        # make the request
        related_payload = dict()
        result_dict = dict()
        for request_json in self.related_queries_widget_list:
            # ensure we know which keyword we are looking at rather than relying on order
            kw = request_json['request']['restriction']['complexKeywordsRestriction']['keyword'][0]['value']
            # convert to string as requests will mangle
            related_payload['req'] = json.dumps(request_json['request'])
            related_payload['token'] = request_json['token']
            related_payload['tz'] = self.tz

            # parse the returned json
            rankedList = self._get_data(
                url=GoogleTrendsAPI.RELATED_QUERIES_URL,
                method=GoogleTrendsAPI.GET_METHOD,
                trim_chars=5,
                params=related_payload,
            )[u'default'][u'rankedList']

            # clean data
            for kw in rankedList[0][u'rankedKeyword']:
            	kw[u'value'] = int(kw[u'value'])
            	del kw[u'link']
            	del kw[u'formattedValue']

            for kw in rankedList[1][u'rankedKeyword']:
            	del kw[u'link']
            	kw[u'value'] = kw[u'formattedValue']
            	del kw[u'formattedValue']

            rankedList[1][u'risingKeywords'] = rankedList[1][u'rankedKeyword']
            del rankedList[1][u'rankedKeyword']

            return rankedList

    def trending_searches(self):
        """Request data from Google's Trending Searches section and return a dataframe"""

        # make the request
        forms = {'ajax': 1, 'pn': 'p1', 'htd': '', 'htv': 'l'}
        return self._get_data(
            url=GoogleTrendsAPI.TRENDING_SEARCHES_URL,
            method=GoogleTrendsAPI.POST_METHOD,
            data=forms,
        )['trendsByDateList']

    def top_charts(self, date, cid, geo='US', cat=''):
        """Request data from Google's Top Charts section and return a dataframe"""

        # create the payload
        chart_payload = {'ajax': 1, 'lp': 1, 'geo': geo, 'date': date, 'cat': cat, 'cid': cid}

        # make the request and parse the returned json
        return self._get_data(
            url=GoogleTrendsAPI.TOP_CHARTS_URL,
            method=GoogleTrendsAPI.POST_METHOD,
            params=chart_payload,
        )['data']['entityList']

    def suggestions(self, keyword):
        """Request data from Google's Keyword Suggestion dropdown and return a dictionary"""

        # make the request
        kw_param = urllib.quote(keyword)
        parameters = {'hl': self.hl}

        return self._get_data(
            url=GoogleTrendsAPI.SUGGESTIONS_URL + kw_param,
            params=parameters,
            method=GoogleTrendsAPI.GET_METHOD,
            trim_chars=5
        )['default']['topics']


import pprint
if __name__ == "__main__":
	x = GoogleTrendsAPI('','')
	x.build_payload(['christmas shirt'])
	#print x.suggestions('iron')
	print x.related_queries()
	#pprint.pprint(x.interest_over_time())
	#test = [{u'formattedTime': u'Aug 14 - Aug 20 2016', u'formattedAxisTime': u'Aug 14, 2016', u'value': 58, u'time': 1471132800}, {u'formattedTime': u'Aug 21 - Aug 27 2016', u'formattedAxisTime': u'Aug 21, 2016', u'value': 73, u'time': 1471737600}, {u'formattedTime': u'Aug 28 - Sep 3 2016', u'formattedAxisTime': u'Aug 28, 2016', u'value': 53, u'time': 1472342400}, {u'formattedTime': u'Sep 4 - Sep 10 2016', u'formattedAxisTime': u'Sep 4, 2016', u'value': 53, u'time': 1472947200}, {u'formattedTime': u'Sep 11 - Sep 17 2016', u'formattedAxisTime': u'Sep 11, 2016', u'value': 79, u'time': 1473552000}, {u'formattedTime': u'Sep 18 - Sep 24 2016', u'formattedAxisTime': u'Sep 18, 2016', u'value': 43, u'time': 1474156800}, {u'formattedTime': u'Sep 25 - Oct 1 2016', u'formattedAxisTime': u'Sep 25, 2016', u'value': 34, u'time': 1474761600}, {u'formattedTime': u'Oct 2 - Oct 8 2016', u'formattedAxisTime': u'Oct 2, 2016', u'value': 51, u'time': 1475366400}, {u'formattedTime': u'Oct 9 - Oct 15 2016', u'formattedAxisTime': u'Oct 9, 2016', u'value': 61, u'time': 1475971200}, {u'formattedTime': u'Oct 16 - Oct 22 2016', u'formattedAxisTime': u'Oct 16, 2016', u'value': 69, u'time': 1476576000}, {u'formattedTime': u'Oct 23 - Oct 29 2016', u'formattedAxisTime': u'Oct 23, 2016', u'value': 51, u'time': 1477180800}, {u'formattedTime': u'Oct 30 - Nov 5 2016', u'formattedAxisTime': u'Oct 30, 2016', u'value': 43, u'time': 1477785600}, {u'formattedTime': u'Nov 6 - Nov 12 2016', u'formattedAxisTime': u'Nov 6, 2016', u'value': 67, u'time': 1478390400}, {u'formattedTime': u'Nov 13 - Nov 19 2016', u'formattedAxisTime': u'Nov 13, 2016', u'value': 85, u'time': 1478995200}, {u'formattedTime': u'Nov 20 - Nov 26 2016', u'formattedAxisTime': u'Nov 20, 2016', u'value': 84, u'time': 1479600000}, {u'formattedTime': u'Nov 27 - Dec 3 2016', u'formattedAxisTime': u'Nov 27, 2016', u'value': 49, u'time': 1480204800}, {u'formattedTime': u'Dec 4 - Dec 10 2016', u'formattedAxisTime': u'Dec 4, 2016', u'value': 71, u'time': 1480809600}, {u'formattedTime': u'Dec 11 - Dec 17 2016', u'formattedAxisTime': u'Dec 11, 2016', u'value': 65, u'time': 1481414400}, {u'formattedTime': u'Dec 18 - Dec 24 2016', u'formattedAxisTime': u'Dec 18, 2016', u'value': 91, u'time': 1482019200}, {u'formattedTime': u'Dec 25 - Dec 31 2016', u'formattedAxisTime': u'Dec 25, 2016', u'value': 89, u'time': 1482624000}, {u'formattedTime': u'Jan 1 - Jan 7 2017', u'formattedAxisTime': u'Jan 1, 2017', u'value': 51, u'time': 1483228800}, {u'formattedTime': u'Jan 8 - Jan 14 2017', u'formattedAxisTime': u'Jan 8, 2017', u'value': 36, u'time': 1483833600}, {u'formattedTime': u'Jan 15 - Jan 21 2017', u'formattedAxisTime': u'Jan 15, 2017', u'value': 36, u'time': 1484438400}, {u'formattedTime': u'Jan 22 - Jan 28 2017', u'formattedAxisTime': u'Jan 22, 2017', u'value': 47, u'time': 1485043200}, {u'formattedTime': u'Jan 29 - Feb 4 2017', u'formattedAxisTime': u'Jan 29, 2017', u'value': 58, u'time': 1485648000}, {u'formattedTime': u'Feb 5 - Feb 11 2017', u'formattedAxisTime': u'Feb 5, 2017', u'value': 47, u'time': 1486252800}, {u'formattedTime': u'Feb 12 - Feb 18 2017', u'formattedAxisTime': u'Feb 12, 2017', u'value': 23, u'time': 1486857600}, {u'formattedTime': u'Feb 19 - Feb 25 2017', u'formattedAxisTime': u'Feb 19, 2017', u'value': 55, u'time': 1487462400}, {u'formattedTime': u'Feb 26 - Mar 4 2017', u'formattedAxisTime': u'Feb 26, 2017', u'value': 23, u'time': 1488067200}, {u'formattedTime': u'Mar 5 - Mar 11 2017', u'formattedAxisTime': u'Mar 5, 2017', u'value': 45, u'time': 1488672000}, {u'formattedTime': u'Mar 12 - Mar 18 2017', u'formattedAxisTime': u'Mar 12, 2017', u'value': 80, u'time': 1489276800}, {u'formattedTime': u'Mar 19 - Mar 25 2017', u'formattedAxisTime': u'Mar 19, 2017', u'value': 62, u'time': 1489881600}, {u'formattedTime': u'Mar 26 - Apr 1 2017', u'formattedAxisTime': u'Mar 26, 2017', u'value': 23, u'time': 1490486400}, {u'formattedTime': u'Apr 2 - Apr 8 2017', u'formattedAxisTime': u'Apr 2, 2017', u'value': 86, u'time': 1491091200}, {u'formattedTime': u'Apr 9 - Apr 15 2017', u'formattedAxisTime': u'Apr 9, 2017', u'value': 32, u'time': 1491696000}, {u'formattedTime': u'Apr 16 - Apr 22 2017', u'formattedAxisTime': u'Apr 16, 2017', u'value': 63, u'time': 1492300800}, {u'formattedTime': u'Apr 23 - Apr 29 2017', u'formattedAxisTime': u'Apr 23, 2017', u'value': 39, u'time': 1492905600}, {u'formattedTime': u'Apr 30 - May 6 2017', u'formattedAxisTime': u'Apr 30, 2017', u'value': 94, u'time': 1493510400}, {u'formattedTime': u'May 7 - May 13 2017', u'formattedAxisTime': u'May 7, 2017', u'value': 47, u'time': 1494115200}, {u'formattedTime': u'May 14 - May 20 2017', u'formattedAxisTime': u'May 14, 2017', u'value': 42, u'time': 1494720000}, {u'formattedTime': u'May 21 - May 27 2017', u'formattedAxisTime': u'May 21, 2017', u'value': 34, u'time': 1495324800}, {u'formattedTime': u'May 28 - Jun 3 2017', u'formattedAxisTime': u'May 28, 2017', u'value': 42, u'time': 1495929600}, {u'formattedTime': u'Jun 4 - Jun 10 2017', u'formattedAxisTime': u'Jun 4, 2017', u'value': 49, u'time': 1496534400}, {u'formattedTime': u'Jun 11 - Jun 17 2017', u'formattedAxisTime': u'Jun 11, 2017', u'value': 100, u'time': 1497139200}, {u'formattedTime': u'Jun 18 - Jun 24 2017', u'formattedAxisTime': u'Jun 18, 2017', u'value': 33, u'time': 1497744000}, {u'formattedTime': u'Jun 25 - Jul 1 2017', u'formattedAxisTime': u'Jun 25, 2017', u'value': 34, u'time': 1498348800}, {u'formattedTime': u'Jul 2 - Jul 8 2017', u'formattedAxisTime': u'Jul 2, 2017', u'value': 85, u'time': 1498953600}, {u'formattedTime': u'Jul 9 - Jul 15 2017', u'formattedAxisTime': u'Jul 9, 2017', u'value': 42, u'time': 1499558400}, {u'formattedTime': u'Jul 16 - Jul 22 2017', u'formattedAxisTime': u'Jul 16, 2017', u'value': 68, u'time': 1500163200}, {u'formattedTime': u'Jul 23 - Jul 29 2017', u'formattedAxisTime': u'Jul 23, 2017', u'value': 42, u'time': 1500768000}, {u'formattedTime': u'Jul 30 - Aug 5 2017', u'formattedAxisTime': u'Jul 30, 2017', u'value': 41, u'time': 1501372800}]
	#pprint.pprint(test)
	#print test











