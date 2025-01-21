from msldap.commons.factory import LDAPConnectionFactory
from msldap.ldap_objects import MSADGPO
import msldap.protocol.typeconversion
import pprint


def patch():

	def single_int(x, encode = False):
		if encode is False:
			return int(x[0])
		return [str(x[0]).encode()]

	
	msldap.protocol.typeconversion.MSLDAP_BUILTIN_ATTRIBUTE_TYPES['versionNumber'] = single_int