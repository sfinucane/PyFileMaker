# PyFileMaker - Integrating FileMaker and Python
# (c) 2014-2014 Marcin Kawa, kawa@aeguana.com
# (c) 2006-2008 Klokan Petr Pridal, klokan@klokan.cz
# (c) 2002-2006 Pieter Claerhout, pieter@yellowduck.be
# 
# http://code.google.com/p/pyfilemaker/
# http://www.yellowduck.be/filemaker/

# Import the main modules
import sys
import re
import base64
import string
import urllib
import requests
import collections
from datetime import date, time
import StringIO
try:
	from google.appengine.api import urlfetch
except:
	urlfetch = False
import httplib	
from exceptions import StandardError

# Import the FM modules
import xml2obj
import FMResultset
from FMError import *

uu = urllib.urlencode

class FMServer:
	"""The main class for communicating with FileMaker Server"""

	def __init__(self, url='http://login:password@localhost/', db='', layout='', debug=False):
		"""Class constructor"""

		self._url = url

		m = re.match(r'^((?P<protocol>http)://)?((?P<login>\w+)(:(?P<password>\w+))?@)?(?P<host>[\d\w\.]+)(:(?P<port>\d+))?/?(?P<address>/.+)?$', self._url)
		if not m:
			raise FMError, "Address of FileMaker Server is not correctly formatted"

		self._protocol = m.group('protocol')
		self._login = m.group('login')
		self._password = m.group('password')
		self._host = m.group('host')
		self._port = m.group('port')
		self._address = m.group('address')

		if not self._protocol: self._protocol = 'http'
		if not self._host: self._host = 'localhost'
		if not self._port: self._port = 80
		if not self._address: self._address = '/fmi/xml/fmresultset.xml'
		if not self._login: self._login = 'pyfilemaker'
		if not self._password: self._password = ''

		self._file_address = 'fmi/xml/cnt/data.%(extension)s'
		self._extra_script = None
		
		self._maxRecords = 0
		self._skipRecords = 0

		self._db = db
		self._layout = layout
		self._lop = 'and'

		self._dbParams = []
		self._sortParams = []

		self._debug = debug
		if '--debug' in sys.argv and not debug:
			self._debug = True

	def setDb(self, db):
		"""Select the database to use. You don't need to specify the file
		extension. PyFileMaker will do this automatically."""
		
		self._db = db

	def setLayout(self, layout):
		"""Select the right layout from the database."""

		self._layout = layout

	def _setMaxRecords(self, maxRec):
		"""Specifies the maximum number of records you want returned (number or constant 'all')"""

		if type(maxRec) == int:
			self._maxRecords = maxRec
		elif type(maxRec) == str and (maxRec.lower == 'all' or maxRec.isdigit()):
			self._maxRecords = maxRec.lower
		else:
			raise FMError, 'Unsupported -max value (not a number or "all").'

	def _setSkipRecords(self, skipRec):
		"""Specifies how many records to skip in the found set"""

		if type(skipRec) == int or (type(skipRec) == str and skipRec.isdigit()):
			self._skipRecords = skipRec
		else:
			raise FMError, 'Unsupported -skip value (not a number).'

	def _setLogicalOperator(self, lop):
		"""Sets the way the find fields should be combined together."""

		if not lop.lower() in ['and', 'or']:
			raise FMError, 'Unsupported logical operator (not one of "and" or "or").'

		self._lop = lop.lower()

	def _setComparasionOperator(self, field, oper):
		"""Sets correct operator for given string representation"""

		if oper != '':
			validOperators = {
				'eq':'eq',
				'equals':'eq',
				'=':'eq',
				'==':'eq',
				'cn':'cn',
				'contains':'cn',
				'%%':'cn',
				'%':'cn',
				'*':'cn',
				'bw':'bw',
				'begins with':'bw',
				'^':'bw',
				'ew':'ew',
				'ends with':'ew',
				'$':'ew',
				'gt':'gt',
				'greater than':'gt',
				'>':'gt',
				'gte':'gte',
				'greater than or equals':'gte',
				'>=':'gte',
				'lt':'lt',
				'less than':'lt',
				'<':'lt',
				'lte':'lte',
				'less than or equals':'lte',
				'<=':'lte',
				'neq':'neq',
				'not equals':'neq',
				'!=':'neq',
				'<>':'neq'
			}

		if not string.lower(oper) in validOperators.keys():
			raise FMError, 'Invalid operator "'+ oper + '" for "' + field + '"'

		oper = validOperators[oper.lower()]
		self._dbParams.append(
			["%s.op" % field, oper]
		)

	def _addDBParam(self, name, value):
		"""Adds a database parameter"""

		if name[-4:] == '__OP':
			return self._setComparasionOperator(name[:-4], value)
		if name[-3:] == '.op':
			return self._setComparasionOperator(name[:-3], value)
		if name.find('__') != -1:
			import re
			name = name.replace('__','::')
		elif name.find('.') != -1:
			name = name.replace('.','::')

		self._dbParams.append(
			[name, value]
		)

	def _addSortParam(self, field, order=''):
		"""Adds a sort parameter, order have to be in ['ascend', 'ascending','descend', 'descending','custom']"""

		if order != '':
			validSortOrders = {
				'ascend':'ascend',
				'ascending':'ascend',
				'<':'ascend',
				'descend':'descend',
				'descending':'descend',
				'>':'descend'
			}

			if not string.lower(order) in validSortOrders.keys():
				raise FMError, 'Invalid sort order for "' + field + '"'
		
		self._sortParams.append(
			[field, validSortOrders[string.lower(order)]]
		)

	def _checkRecordID(self):
		"""This function will check if a record ID was specified."""

		hasRecID = 0

		for dbParam in self._dbParams:
			if dbParam[0] == 'RECORDID':
				hasRecID = 1
				break

		return hasRecID

	def getFile(self, file_xml_uri):
		""" This will execute cmd to fetch file data from FMServer """
		find = re.match('/fmi/xml/cnt/([\w\d.-]+)\.([\w]+)?-*', file_xml_uri)

		file_name = find.group(1)
		file_extension = find.group(2)
		file_binary = self._doRequest(is_file=True, file_xml_uri=file_xml_uri)
		return (file_name, file_extension, file_binary)

	def doScript(self, script_name, params=None):
		"""This function executes the script for given layout for the current db."""
		request = [
			uu({'-db': self._db }),
			uu({'-lay': self._layout }),
			uu({'-script': script_name})
		]

		if params:
			request.append(uu({'-script.param': params }))

		request.append(uu({'-findall': '' }))

		result = self._doRequest(request)
		result = FMResultset.FMResultset(result)

		return result.resultset[0] # Return latest result

	def doScriptAfter(self, func, func_kwargs={}, script_name='', params=None):
		""" This function will execute extra script after passed function """
		request = [
			uu({'-script': script_name})
		]

		if params:
			request.append(uu({'-script.param': params }))

		self._extra_script = request

		return func(**func_kwargs)

	def doFindQuery(self, query_dict, negate_fields={}):
		query_params = []
		query_values = []

		_idx = 1
		for counter, t in enumerate(query_dict.iteritems()):
			idx = counter + _idx
			key = t[0]
			key_value = t[1]
			if not isinstance(key_value, str) and isinstance(key_value, collections.Iterable):
				for inner_counter, inner_value in enumerate(key_value):
					inner_idx = inner_counter + idx

					query_params.append("%s(q%s)"%(negate_fields.get(key, ''), inner_idx))
					query_values.append(uu({'-q%s'%inner_idx: key}))
					query_values.append(uu({'-q%s.value'%inner_idx: inner_value}))

					_idx = inner_idx - 1
			else:
				query_params.append("%s(q%s)"%(negate_fields.get(key, ''), idx))
				query_values.append(uu({'-q%s'%idx: key}))
				query_values.append(uu({'-q%s.value'%idx: key_value}))

		query_params_str = ';'.join(query_params)

		request = [
			uu({'-db': self._db }),
			uu({'-lay': self._layout }),
			'-query=%s'%query_params_str
		]
		request += query_values
		request.append('-findquery')

		result = self._doRequest(request)
		result = FMResultset.FMResultset(result)

		return result.resultset

	def getDbNames(self):
		"""This function returns the list of open databases"""
	
		request = []
		request.append(uu({'-dbnames': '' }))

		result = self._doRequest(request)
		result = FMResultset.FMResultset(result)

		dbNames = []
		for dbName in result.resultset:
			dbNames.append(string.lower(dbName['DATABASE_NAME']))
		
		return dbNames

	def getLayoutNames(self):
		"""This function returns the list of layouts for the current db."""

		if self._db == '':
			raise FMError, 'No database was selected'
	
		request = []
		request.append(uu({'-db': self._db }))
		request.append(uu({'-layoutnames': '' }))

		result = self._doRequest(request)
		result = FMResultset.FMResultset(result)

		layoutNames = []
		for layoutName in result.resultset:
			layoutNames.append(string.lower(layoutName['LAYOUT_NAME']))

		return layoutNames

	def getScriptNames(self):
		"""This function returns the list of layouts for the current db."""

		if self._db == '':
			raise FMError, 'No database was selected'

		request = []
		request.append(uu({'-db': self._db }))
		request.append(uu({'-scriptnames': '' }))

		result = self._doRequest(request)
		result = FMResultset.FMResultset(result)

		scriptNames = []
		for scriptName in result.resultset:
			scriptNames.append(string.lower(scriptName['SCRIPT_NAME']))

		return scriptNames

	def _preFind(self, WHAT={}, SORT=[], SKIP=None, MAX=None, LOP='AND'):
		"""This function will process attributtes for all -find* commands."""

		if hasattr(WHAT, '_modified'):
			self._addDBParam('RECORDID', WHAT.RECORDID)
		elif type(WHAT)==dict:
			for key in WHAT:
				self._addDBParam(key, WHAT[key])
		else:
			raise FMError, 'Python Runtime: Object type (%s) given to on of function doFind* as argument WHAT cannot be used.' % type(WHAT)

		for key in SORT:
			self._addSortParam(key, SORT[key])

		if SKIP: self._setSkipRecords(SKIP)
		if MAX: self._setMaxRecords(MAX)
		if LOP: self._setLogicalOperator(LOP)

		if self._layout == '':
			raise FMError, 'No layout was selected'

	def doFind(self, WHAT={}, SORT=[], SKIP=None, MAX=None, LOP='AND', **params):
		"""This function will perform the command -find."""

		self._preFind(WHAT, SORT, SKIP, MAX, LOP)

		for key in params:
			self._addDBParam(key, params[key])

		return self._doAction('-find')

	def doFindAll(self, WHAT={}, SORT=[], SKIP=None, MAX=None):
		"""This function will perform the command -findall."""

		self._preFind(WHAT, SORT, SKIP, MAX)

		return self._doAction('-findall')

	def doFindAny(self, WHAT={}, SORT=[], SKIP=None, MAX=None, LOP='AND', **params):
		"""This function will perform the command -findany."""

		self._preFind(WHAT, SORT, SKIP, MAX, LOP)

		for key in params:
			self._addDBParam(key, params[key])

		return self._doAction('-findany')

	def doDelete(self, WHAT={}):
		"""This function will perform the command -delete."""

		if hasattr(WHAT, '_modified'):
			self._addDBParam('RECORDID', WHAT.RECORDID)
			self._addDBParam('MODID', WHAT.MODID)
		elif type(WHAT) == dict and WHAT.has_key('RECORDID'):
			self._addDBParam('RECORDID', WHAT['RECORDID'])
		else:
			raise FMError, 'Python Runtime: Object type (%s) given to function doDelete as argument WHAT cannot be used.' % type(WHAT)

		if self._layout == '':
			raise FMError, 'No layout was selected'

		if self._checkRecordID() == 0:
			raise FMError, 'RecordID is missing'

		return self._doAction('-delete')

	def doEdit(self, WHAT={}, **params):
		"""This function will perform the command -edit."""

		if hasattr(WHAT, '_modified'):
			for key, value in WHAT._modified():
				if WHAT.__new2old__.has_key(key):
					self._addDBParam(WHAT.__new2old__[key].encode('utf-8'), value)
				else:	
					self._addDBParam(key, value)
			self._addDBParam('RECORDID', WHAT.RECORDID)
			self._addDBParam('MODID', WHAT.MODID)
		elif type(WHAT)==dict:
			for key in WHAT:
				self._addDBParam(key, WHAT[key])
		else:
			raise FMError, 'Python Runtime: Object type (%s) given to function doEdit as argument WHAT cannot be used.' % type(WHAT)

		if self._layout == '':
			raise FMError, 'No layout was selected'

		for key in params:
			self._addDBParam(key, params[key])

		if len(self._dbParams) == 0:
			raise FMError, 'No data to be edited'

		if self._checkRecordID() == 0:
			raise FMError, 'RecordID is missing'

		return self._doAction('-edit')

	def doNew(self, WHAT={}, **params):
		"""This function will perform the command -new."""

		if hasattr(WHAT, '_modified'):
			for key in WHAT:
				if key not in ['RECORDID','MODID']:
					if WHAT.__new2old__.has_key(key):
						self._addDBParam(WHAT.__new2old__[key].encode('utf-8'), WHAT[key])
					else:	
						self._addDBParam(key, WHAT[key])
		elif type(WHAT)==dict:
			for key in WHAT:
				self._addDBParam(key, WHAT[key])
		else:
			raise FMError, 'Python Runtime: Object type (%s) given to function doNew as argument WHAT cannot be used.' % type(WHAT)

		if self._layout == '':
			raise FMError, 'No layout was selected'

		for key in params:
			self._addDBParam(key, params[key])

		if len(self._dbParams) == 0:
			raise FMError, 'No data to be added'

		return self._doAction('-new')

	def doView(self):
		"""This function will perform the command -view. (Retrieves the metadata section of XML document and an empty recordset)"""

		if self._layout == '':
			raise FMError, 'No layout was selected'

		return self._doAction('-view')

	def doDup(self, WHAT={}, **params):
		"""This function will perform the command -dup."""

		if hasattr(WHAT, '_modified'):
			for key, value in WHAT._modified():
				if WHAT.__new2old__.has_key(key):
					self._addDBParam(WHAT.__new2old__[key].encode('utf-8'), value)
				else:	
					self._addDBParam(key, value)
			self._addDBParam('RECORDID', WHAT.RECORDID)
			self._addDBParam('MODID', WHAT.MODID)
		elif type(WHAT) == dict:
			for key in WHAT:
				self._addDBParam(key, WHAT[key])
		else:
			raise FMError, 'Python Runtime: Object type (%s) given to function doDup as argument WHAT cannot be used.' % type(WHAT)

		if self._layout == '':
			raise FMError, 'No layout was selected'

		for key in params:
			self._addDBParam(key, params[key])

		if self._checkRecordID() == 0:
			raise FMError, 'RecordID is missing'

		return self._doAction('-dup')

	def _doAction(self, action):
		"""This function will perform a FileMaker action."""

		if self._db == '':
			raise FMError, 'No database was selected'

		result = ''

		try:
			request = [
				uu({'-db': self._db })
			]

			if self._layout != '':
				request.append(uu({'-lay': self._layout }))

			if action == '-find' and self._lop != 'and':
				request.append(uu({'-lop': self._lop }))

			if action in ['-find', '-findall']:

				if self._skipRecords != 0:
					request.append(uu({ '-skip': self._skipRecords }))

				if self._maxRecords != 0:
					request.append(uu({ '-max': self._maxRecords }))

				for i in range(0, len(self._sortParams)):
					sort = self._sortParams[i]
					request.append(uu({ '-sortfield.'+str(i+1): sort[0] }))

					if sort[1] != '':
						request.append(uu({ '-sortorder.'+str(i+1): sort[1] }))

			for dbParam in self._dbParams:

				if dbParam[0] == 'RECORDID':
					request.append(uu({ '-recid': dbParam[1] }))
				
				elif dbParam[0] == 'MODID':
					request.append(uu({ '-modid': dbParam[1] }))

				elif hasattr(dbParam[1], 'strftime'):
					d = dbParam[1]
					if (not hasattr(d, 'second')):
						request.append(uu({ dbParam[0]: d.strftime('%m-%d-%Y') }))
					else:
						request.append(uu({ dbParam[0]: d.strftime('%m-%d-%Y %H:%M:%S') }))
					del(d)
				else:
					request.append(uu({ dbParam[0]: dbParam[1] }))
			request.append(action)

			if self._extra_script:
				request += self._extra_script
				self._extra_script = None

			result = self._doRequest(request)
			
			try:
				result = FMResultset.FMResultset(result)
			except FMFieldError, value:
				realfields = FMServer(self._buildUrl(), self._db, self._layout).doView()

				l = []
				for k, v in self._dbParams:
					if k[-3:] != '.op' and k[0] != '-':
						l.append(("'%s'" % k.replace('::','.')).encode('utf-8'))
				raise FMError, "Field(s) %s not found on layout '%s'" % (', '.join(l), self._layout)

			if action == '-view':
				result = result.fieldNames

		finally:
			self._dbParams = []
			self._sortParams = []
			self._skipRecords = 0
			self._maxRecords = 0
			self._lop = 'and'

		return result

	def _buildUrl(self):
		"""Builds url for normal FM requests."""
		return '%(protocol)s://%(host)s:%(port)s/%(address)s'%{
			'protocol': self._protocol,
			'host': self._host,
			'port': self._port,
			'address': self._address,
		}
	
	def _buildFileUrl(self, xml_req):
		"""Builds url for fetching the files from FM."""
		return '%(protocol)s://%(host)s:%(port)s%(xml_req)s'%{
			'protocol': self._protocol,
			'host': self._host,
			'port': self._port,
			'xml_req': xml_req,
		}

	def _doRequest(self, request=None, is_file=False, file_xml_uri=''):
		"""This function will perform the specified request on the FileMaker
		server, and it will return the raw result from FileMaker."""
		if request is None:
			request = []

		if is_file and file_xml_uri:
			url = self._buildFileUrl(file_xml_uri)
		else:
			request = '&'.join(request)
			url = "%s?%s" % (self._buildUrl(), request)

		resp = requests.get(
			url = url,
			auth = (self._login, self._password)
		)

		return resp.content
