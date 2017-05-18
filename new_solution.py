import os
import os.path
import sys
import glob
import json
import logging
import jmespath

logger = logging.getLogger('converter')

class ConverterError(Exception):
    pass


class Converter(object):

    VALID_POSITIONS = ["Син",
            "Дружина",
            "Чоловік",
            "Донька",
            "Дочка",
            "Мати",
            "Батько",
            "Жінка",
            "Брат",
            "Дружина брата",
            "Сестра",
            "Теща",
            "Онук",
            "Мама",
            "Невістка",
            "Племінник",
            "Баба",
            "Пасинок",
            "Дитина",
            "Матір",
            "Онука",
            "Зять",
            "Діти",
            "Свекор",
            "Бабуся",
            "Племінниця",
            "Донечка",
            "Тесть",
            "Внучка",
            "Сын",
            "Чоловик",
            "Співмешканець",
            "Супруга",
            "Допька",
            "Дружіна",
            "Падчерка",
            "Внук",
            "Свекруха",
            "Мать",
            "Доч",
            "Батьки",
            "Тітка",
            "Співмешканака",
            "Онучка",
            "Тато",
            "Жена"]

    def __init__(self, src):
        self.src = src

        if (src['id'].lower().startswith('nacp_')):
            raise ConverterError(
                "Declaration {} already has new format".format(src["id"]))

    def _jsrch(self, path, doc=None):
        if doc is None:
            doc = self.src

        return jmespath.search(path, doc)

    def _convert_space_values(self, totalArea, areaUnits):
        areas_koef = {
          "га": 10000,
          "cоток": 100
        }
        try:        
            totalArea = totalArea.replace(',', '.')

            if not totalArea:
                return 0

            if not areaUnits:
                return float(totalArea)

            return float(totalArea) * areas_koef.get(areaUnits, 1)
        except ValueError:
            logging.debug("Can not convert string to float. Set to '0'.")
            return 0

    def _parse_family_member(self, string):
        try:
            position, person = string.split(None, 1)
            if "-" in position:
                position, person = string.split("-", 1)

            position = position.strip(u" -—,.:").capitalize()
            person = person.strip(u" -—,")

            if position not in self.VALID_POSITIONS:
                raise ValueError

            for pos in self.VALID_POSITIONS:
                if person.capitalize().startswith(pos):
                    print("%s %s %s" % (string, person, pos))
                    raise ValueError

            return {
                "relations": position,
                "family_name": person
            }
        except ValueError:
            return {"raw": string}

    def _parse_raw_family_string(self, family_raw):
        return map(self._parse_family_member,
                   filter(None, family_raw.split(";")))

    def _meta_information(self):
        new_doc = self._convert_using_rules(
            [
                ("id", "id", ""),
                ("declaration.date", "created_date", ""),
                ("declaration.date", "lastmodified_date", ""),
                (None, "data", {})
            ]
        )

        return new_doc

    def _convert_using_rules(self, rules, source=None):
        subdoc = {}

        for oldpath, new_key, default in rules:
            if not oldpath:
                subdoc[new_key] = default
            else:
                subdoc[new_key] = self._jsrch(oldpath, source) or default

        return subdoc

    def _convert_step0(self):
        extract = self._convert_using_rules(
            [
                ("intro.declaration_type", "declarationType", "1"),
                ("intro.declaration_year", "declarationYear1", "")
            ]
        )

        return {
            "step_0": extract
        }

    def _convert_step1(self):
        extract = self._convert_using_rules(
            [
                ("general.name", "firstname", ""),
                ("general.last_name", "lastname", ""),
                ("general.patronymic", "middlename", ""),
                ("general.post.region", "region_declcomua", ""),
                ("general.post.post", "workPost", ""),
                ("general.post.office", "workPlace", ""),
                ("general.addresses_raw", "actual_street", ""),
                (None, "region", ""),
                (None, "district", ""),
                (None, "city", ""),
                (None, "street", "")
            ]
        )

        # added 'addresses_raw' as 'actual_street'
        # in case there is no "general.addresses" in old_json
        addresses = self._jsrch("general.addresses")
        if addresses:
            current_address = addresses[0]
            extract['region'] = current_address.get("place", "")
            extract['district'] = current_address.get("place_district", "")
            extract['city'] = current_address.get("place_city", "")
            extract['street'] = current_address.get("place_address", "")

        return {
            "step_1": extract
        }

    def _convert_step2(self):
        family_info = self._jsrch("general.family")
        raw_family_info = self._jsrch("general.family_raw")
        extract = {}

        if family_info:
            for i, fm_member in enumerate(family_info, 1):
                extract[i] = self._convert_using_rules(
                    [
                        ("name_hidden", "changedName", ""),
                        ("relations", "subjectRelation", ""),
                        ("family_name", "bio_declomua", ""),
                        (None, 'citizenship', ""),
                        (None, 'eng_lastname', ""),
                        (None, 'no_taxNumber', ""),
                        (None, 'eng_firstname', ""),
                        (None, 'eng_middlename', ""),
                        (None, 'isNotApplicable', ""),
                        (None, 'previous_lastname', ""),
                        (None, 'previous_firstname', ""),
                        (None, 'previous_middlename', ""),
                        (None, 'previous_eng_lastname', ""),
                        (None, 'previous_eng_firstname', ""),
                        (None, 'previous_eng_middlename', "")
                    ],
                    fm_member   
                )
                if extract[i]["subjectRelation"].lower() == "інше" and \
                   "relations_other" in fm_member:
                   extract[i]["subjectRelation"] += \
                                    ", " + fm_member["relations_other"]
        elif raw_family_info:
            for i, fm_member in enumerate(self._parse_raw_family_string(
                                                raw_family_info)):
                extract[i] = {}
                extract[i]["raw"] = fm_member.get("raw", "")
                extract[i]["subjectRelation"] = fm_member.get("relations", "")
                extract[i]["bio_declomua"] = fm_member.get("family_name", "")
        
        return {
            "step_2": extract
        }

    def _convert_step3(self):
        extract = {}
        record_counter = 1
        estate_desc_dict = {
            '23': 'Земельна ділянка',
            '24': 'Житловий будинок',
            '25': 'Квартира',
            '26': 'Садовий (дачний) будинок',
            '27': 'Гараж',
            '28': 'Інше нерухоме майно',
            '29': 'Земельна ділянка',
            '30': 'Житловий будинок',
            '31': 'Квартира',
            '32': 'Садовий (дачний) будинок',
            '33': 'Гараж',
            '34': 'Інше нерухоме майно'
        }
        estate_info = self._jsrch("estate")
        if estate_info:
            for estate_id, estate_items in estate_info.items():
                owner_id = ('1'
                            if int(estate_id) in range(23, 29)
                            else 'family')
                if not estate_items:
                    continue

                for estate in estate_items:
                    if estate.get('space'):
                        extract[record_counter] = \
                            self._convert_using_rules(
                                [
                                 (None, 'city', ""),
                                 (None, 'person', ""),
                                 ('region', 'place_oblast_declcomua', ""),
                                 ('address', 'place_address_declcomua', ""),
                                 (None, 'rights', {}),
                                 (None, 'country', ""),
                                 (None, 'cityPath', ""),
                                 ('costs', 'costDate', ""),
                                 (None, 'district', ""),
                                 (None, 'postCode', ""),
                                 (None, 'iteration', ""),
                                 ('space', 'totalArea', ""),
                                 (None, 'ua_street', ""),
                                 (None, 'objectType', ""),
                                 (None, 'owningDate', ""),
                                 (None, 'objectType', ""),
                                 ('region', 'ua_cityType', ""),
                                 (None, 'ua_postCode', ""),
                                 ('address', 'ua_streetType', ""),
                                 (None, 'costAssessment', ""),
                                 (None, 'otherObjectType', ""),
                                 ('costs_rent', 'costRent_declcomua', ""),
                                 (None, 'costAssessment_extendedstatus', ""),
                                 (None, 'ua_housePartNum_extendedstatus', ""),
                                 (None, 'ua_apartmentsNum_extendedstatus', "")
                                ],
                                estate
                        )
                        extract[record_counter]['objectType'] = \
                            estate_desc_dict[estate_id]

                        totalArea = extract[record_counter]['totalArea']
                        spaceUnits = self._jsrch('space_units', estate)

                        extract[record_counter]['totalArea'] = \
                            self._convert_space_values(totalArea,
                                                       spaceUnits
                        )
                        extract[record_counter]['rights'][owner_id] = \
                            self._convert_using_rules(
                                [
                                 (None, 'citizen', ""),
                                 (None, 'ua_city', ""),
                                 (None, 'ua_street', ""),
                                 (None, 'ua_lastname', ""),
                                 (None, 'ua_postCode', ""),
                                 (None, 'eng_lastname', ""),
                                 (None, 'eng_postCode', ""),
                                 (None, 'rightBelongs', owner_id),
                                 (None, 'ua_firstname', ""),
                                 (None, 'ukr_lastname', ""),
                                 (None, 'eng_firstname', ""),
                                 (None, 'ownershipType', ""),
                                 (None, 'ua_middlename', ""),
                                 (None, 'ua_streetType', ""),
                                 (None, 'ukr_firstname', ""),
                                 (None, 'eng_middlename', ""),
                                 (None, 'otherOwnership', ""),
                                 (None, 'ukr_middlename', ""),
                                 (None, 'rights_cityPath', ""),
                                 (None, 'ua_company_name', ""),
                                 (None, 'eng_company_name', ""),
                                 (None, 'ukr_company_name', ""),
                                 (None, 'percent-ownership', '100'),
                                 (None, 'ua_street_extendedstatus', ""),
                                 (None, 'ua_houseNum_extendedstatus', ""),
                                 (None, 'ua_postCode_extendedstatus', ""),
                                 (None, 'eng_postCode_extendedstatus', ""),
                                 (None, 'ua_middlename_extendedstatus', ""),
                                 (None, 'eng_middlename_extendedstatus', ""),
                                 (None, 'ukr_middlename_extendedstatus', ""),
                                 (None, 'ua_housePartNum_extendedstatus', ""),
                                 (None, 'ua_apartmentsNum_extendedstatus', "")
                                ],
                                estate
                        )
                        if extract[record_counter]['costRent_declcomua']:
                           extract[record_counter]['rights'][owner_id]['ownershipType'] = \
                                'Оренда' 
                        record_counter += 1
        return {
            "step_3": extract
        }

    def _convert_step6(self):
        extract = {}
        record_counter = 1
        vehicle_desc_dict = {
            '35': 'Автомобілі легкові',
            '36': 'Автомобілі вантажні (спеціальні)',
            '37': 'Водні засоби',
            '38': 'Повітряні судна',
            '39': 'Інші засоби',
            '40': 'Автомобілі легкові',
            '41': 'Автомобілі вантажні (спеціальні)',
            '42': 'Водні засоби',
            '43': 'Повітряні судна',
            '44': 'Інші засоби'
        }
        vehicle_info = self._jsrch("vehicle")
        if vehicle_info:
            for vehicle_id, vehicle_items in vehicle_info.items():
                owner_id = ('1'
                            if int(vehicle_id) in range(35,40)
                            else 'family')
                for vehicle in vehicle_items:
                    extract[record_counter] = \
                        self._convert_using_rules(
                            [
                             ('brand', 'brand', ""),
                             ('brand_info', 'model', ""),
                             (None, 'person', ""),
                             (None, 'rights', {}),
                             ('sum', 'costDate', ""),
                             ('sum_rent', 'costRent_declcomua', ""),
                             (None, 'iteration', ""),
                             (None, 'objectType', ""),
                             (None, 'owningDate', ""),
                             ('year', 'graduationYear', ""),
                             (None, 'otherObjectType', "")
                            ],
                            vehicle
                        )
                    extract[record_counter]['objectType'] = \
                            vehicle_desc_dict[vehicle_id]
                    extract[record_counter]['rights'][owner_id] = \
                            self._convert_using_rules(
                                [
                                 (None, 'citizen', ""),
                                 (None, 'ua_city', ""),
                                 (None, 'ua_street', ""),
                                 (None, 'ua_lastname', ""),
                                 (None, 'ua_postCode', ""),
                                 (None, 'eng_lastname', ""),
                                 (None, 'eng_postCode', ""),
                                 (None, 'rightBelongs', owner_id),
                                 (None, 'ua_firstname', ""),
                                 (None, 'ukr_lastname', ""),
                                 (None, 'eng_firstname', ""),
                                 (None, 'ownershipType', ""),
                                 (None, 'ua_middlename', ""),
                                 (None, 'ua_streetType', ""),
                                 (None, 'ukr_firstname', ""),
                                 (None, 'eng_middlename', ""),
                                 (None, 'otherOwnership', ""),
                                 (None, 'ukr_middlename', ""),
                                 (None, 'rights_cityPath', ""),
                                 (None, 'ua_company_name', ""),
                                 (None, 'eng_company_name', ""),
                                 (None, 'ukr_company_name', ""),
                                 (None, 'percent-ownership', '100'),
                                 (None, 'ua_street_extendedstatus', ""),
                                 (None, 'ua_houseNum_extendedstatus', ""),
                                 (None, 'ua_postCode_extendedstatus', ""),
                                 (None, 'eng_postCode_extendedstatus', ""),
                                 (None, 'ua_middlename_extendedstatus', ""),
                                 (None, 'eng_middlename_extendedstatus', ""),
                                 (None, 'ukr_middlename_extendedstatus', ""),
                                 (None, 'ua_housePartNum_extendedstatus', ""),
                                 (None, 'ua_apartmentsNum_extendedstatus', "")
                                ],
                                vehicle
                    )
                    if extract[record_counter]['costRent_declcomua']:
                       extract[record_counter]['rights'][owner_id]['ownershipType'] = \
                            "Оренда"
                    record_counter += 1
        
        return {
            "step_6": extract
        }

    def _convert_step7(self):
        extract = {}
        record_counter = 1
        papers_desc = 'Номінальна вартість цінних паперів'
        papers_info = {}
        papers_info[47] = self._jsrch('banks."47"')
        papers_info[52] = self._jsrch('banks."52"')
        outer_papers_info = self._jsrch('banks."48"')

        if papers_info:
            for paper_id, paper_items in papers_info.items():
                owner_id = ('1'
                            if paper_id == 47
                            else 'family')
                if not paper_items:
                    continue

                for paper in paper_items:
                    if paper.get('sum') or paper.get('sum_foreign'):
                        extract[record_counter] = \
                            self._convert_using_rules(
                            [
                             ('sum', 'cost', ""),
                             (None, 'amount', ""),
                             (None, 'costCurrentYear', ""),
                             (None, 'person', owner_id),
                             (None, 'rights', {}),
                             (None, 'emitent', ""),
                             (None, 'owningDate', ""),
                             (None, 'emitent_type', ""),
                             (None, 'typeProperty', papers_desc),
                             (None, 'otherObjectType', ""),
                             (None, 'subTypeProperty1', ""),
                             (None, 'subTypeProperty2', ""),
                             (None, 'emitent_ua_lastname', ""),
                             (None, 'emitent_eng_fullname', ""),
                             (None, 'sizeAssets_currentYear_declcomua', ""),
                             ('sum_foreign', 'sizeAssets_abroad_declcomua', ""),
                             (None, 'sizeAssets_abroad_currentYear_declcomua', ""),
                             (None, 'emitent_ua_firstname', ""),
                             (None, 'emitent_ukr_fullname', ""),
                             (None, 'emitent_ua_middlename', ""),
                             (None, 'emitent_ua_company_name', ""),
                             (None, 'emitent_eng_company_name', ""),
                             (None, 'emitent_ukr_company_name', ""),
                             (None, 'emitent_ua_sameRegLivingAddress', ""),
                             (None, 'emitent_eng_sameRegLivingAddress', "")
                            ],
                            paper
                        )

                        if paper_id == 47:
                            extract[record_counter]['emitent_type'] = \
                                'Юридична особа, зареєстрована в Україні'
                            if outer_papers_info:
                                extract[record_counter]['sizeAssets_currentYear_declcomua'] = \
                                    self._jsrch('[0].sum', outer_papers_info)
                                extract[record_counter]['sizeAssets_abroad_currentYear_declcomua'] = \
                                    self._jsrch('[0].sum_foreign', outer_papers_info)
                        extract[record_counter]['rights'][owner_id] = \
                            self._convert_using_rules(
                                [
                                 (None, 'citizen', ""),
                                 (None, 'ua_city', ""),
                                 (None, 'ua_street', ""),
                                 (None, 'ua_lastname', ""),
                                 (None, 'ua_postCode', ""),
                                 (None, 'eng_lastname', ""),
                                 (None, 'eng_postCode', ""),
                                 (None, 'rightBelongs', owner_id),
                                 (None, 'ua_firstname', ""),
                                 (None, 'ukr_lastname', ""),
                                 (None, 'eng_firstname', ""),
                                 (None, 'ownershipType', ""),
                                 (None, 'ua_middlename', ""),
                                 (None, 'ua_streetType', ""),
                                 (None, 'ukr_firstname', ""),
                                 (None, 'eng_middlename', ""),
                                 (None, 'otherOwnership', ""),
                                 (None, 'ukr_middlename', ""),
                                 (None, 'rights_cityPath', ""),
                                 (None, 'ua_company_name', ""),
                                 (None, 'eng_company_name', ""),
                                 (None, 'ukr_company_name', ""),
                                 (None, 'percent-ownership', '100'),
                                 (None, 'ua_street_extendedstatus', ""),
                                 (None, 'ua_houseNum_extendedstatus', ""),
                                 (None, 'ua_postCode_extendedstatus', ""),
                                 (None, 'eng_postCode_extendedstatus', ""),
                                 (None, 'ua_middlename_extendedstatus', ""),
                                 (None, 'eng_middlename_extendedstatus', ""),
                                 (None, 'ukr_middlename_extendedstatus', ""),
                                 (None, 'ua_housePartNum_extendedstatus', ""),
                                 (None, 'ua_apartmentsNum_extendedstatus', "")   
                                ],
                                paper
                        )
                        record_counter += 1

        return {    
            "step_7": extract
        }

    def _convert_step8(self):
        extract = {}
        record_counter = 1
        papers_desc = 'Розмір внесків до статутного капіталу товариства, підприємства, організації'
        papers_info = {}
        papers_info[49] = self._jsrch('banks."49"')
        papers_info[53] = self._jsrch('banks."49"')
        outer_papers_info = self._jsrch('banks."50"')

        if papers_info:
            for paper_id, paper_items in papers_info.items():
                owner_id = ('1'
                            if paper_id == 49
                            else 'family')
                if not paper_items:
                    continue

                for paper in paper_items:
                    if paper.get('sum') or paper.get('sum_foreign'):
                        extract[record_counter] = \
                            self._convert_using_rules(
                            [
                             ('sum', 'cost', ""),
                             (None, 'name', ""),
                             (None, 'person', ""),
                             (None, 'rights', {}),
                             (None, 'country', ""),
                             (None, 'en_name', ""),
                             (None, 'typeProperty', papers_desc),
                             (None, 'sizeAssets_currentYear_declcomua', ""),
                             ('sum_foreign', 'sizeAssets_abroad_declcomua', ""),
                             (None, 'sizeAssets_abroad_currentYear_declcomua', ""),
                             (None, 'iteration', ""),
                             (None, 'legalForm', ""),
                             (None, 'cost_percent', "")
                            ],
                            paper
                        )
                        if paper_id == 49 and outer_papers_info:
                            extract[record_counter]['sizeAssets_currentYear_declcomua'] = \
                                self._jsrch('[0].sum', outer_papers_info)
                            extract[record_counter]['sizeAssets_abroad_currentYear_declcomua'] = \
                                self._jsrch('[0].sum_foreign', outer_papers_info)
                        extract[record_counter]['rights'][owner_id] = \
                            self._convert_using_rules(
                                [
                                 (None, 'citizen', ""),
                                 (None, 'ua_city', ""),
                                 (None, 'ua_street', ""),
                                 (None, 'ua_lastname', ""),
                                 (None, 'ua_postCode', ""),
                                 (None, 'eng_lastname', ""),
                                 (None, 'eng_postCode', ""),
                                 (None, 'rightBelongs', owner_id),
                                 (None, 'ua_firstname', ""),
                                 (None, 'ukr_lastname', ""),
                                 (None, 'eng_firstname', ""),
                                 (None, 'ownershipType', ""),
                                 (None, 'ua_middlename', ""),
                                 (None, 'ua_streetType', ""),
                                 (None, 'ukr_firstname', ""),
                                 (None, 'eng_middlename', ""),
                                 (None, 'otherOwnership', ""),
                                 (None, 'ukr_middlename', ""),
                                 (None, 'rights_cityPath', ""),
                                 (None, 'ua_company_name', ""),
                                 (None, 'eng_company_name', ""),
                                 (None, 'ukr_company_name', ""),
                                 (None, 'percent-ownership', '100'),
                                 (None, 'ua_street_extendedstatus', ""),
                                 (None, 'ua_houseNum_extendedstatus', ""),
                                 (None, 'ua_postCode_extendedstatus', ""),
                                 (None, 'eng_postCode_extendedstatus', ""),
                                 (None, 'ua_middlename_extendedstatus', ""),
                                 (None, 'eng_middlename_extendedstatus', ""),
                                 (None, 'ukr_middlename_extendedstatus', ""),
                                 (None, 'ua_housePartNum_extendedstatus', ""),
                                 (None, 'ua_apartmentsNum_extendedstatus', "")   
                                ],
                                paper
                        )
                        record_counter += 1

        return {
            "step_8": extract
        }

    def _convert_step12(self):
        extract = {}
        record_counter = 1
        papers_desc = 'Сума коштів на рахунках у банках та інших фінансових установах'
        papers_info = {}
        papers_info[45] = self._jsrch('banks."45"')
        papers_info[51] = self._jsrch('banks."51"')
        outer_papers_info = self._jsrch('banks."46"')

        if papers_info:
            for paper_id, paper_items in papers_info.items():
                owner_id = ('1'
                            if paper_id == 45
                            else 'family')
                if not paper_items:
                    continue

                for paper in paper_items:
                    if paper.get('sum') or paper.get('sum_foreign'):
                        extract[record_counter] = \
                            self._convert_using_rules(
                                [
                                  (None, 'person', ""),
                                  (None, 'rights', {}),
                                  (None, 'objectType', papers_desc),
                                  ('sum', 'sizeAssets', ""),
                                  (None, 'organization', ""),
                                  (None, 'costCurrentYear', ""),
                                  (None, 'assetsCurrency', 'UAH'),
                                  (None, 'sizeAssets_currentYear_declcomua', ""),
                                  ('sum_foreign', 'sizeAssets_abroad_declcomua', ""),
                                  (None, 'sizeAssets_abroad_currentYear_declcomua', ""),
                                  (None, 'otherObjectType', ""),
                                  (None, 'organization_type', ""),
                                  (None, 'debtor_ua_lastname', ""),
                                  (None, 'debtor_eng_lastname', ""),
                                  (None, 'debtor_ua_firstname', ""),
                                  (None, 'debtor_ukr_lastname', ""),
                                  (None, 'debtor_eng_firstname', ""),
                                  (None, 'debtor_ua_middlename', ""),
                                  (None, 'debtor_ukr_firstname', ""),
                                  (None, 'debtor_eng_middlename', ""),
                                  (None, 'debtor_ukr_middlename', ""),
                                  (None, 'organization_ua_company_name', ""),
                                  (None, 'organization_eng_company_name', ""),
                                  (None, 'organization_ukr_company_name', ""),
                                  (None, 'debtor_ua_sameRegLivingAddress', ""),
                                  (None, 'debtor_eng_sameRegLivingAddress', "")
                                ],
                                paper
                        )
                        if paper_id == 45 and outer_papers_info:
                            extract[record_counter]['sizeAssets_currentYear_declcomua'] = \
                                self._jsrch('[0].sum', outer_papers_info)
                            extract[record_counter]['sizeAssets_abroad_currentYear_declcomua'] = \
                                self._jsrch('[0].sum_foreign', outer_papers_info)
                        extract[record_counter]['rights'][owner_id] = \
                            self._convert_using_rules(
                                [
                                 (None, 'citizen', ""),
                                 (None, 'ua_city', ""),
                                 (None, 'ua_street', ""),
                                 (None, 'ua_lastname', ""),
                                 (None, 'ua_postCode', ""),
                                 (None, 'eng_lastname', ""),
                                 (None, 'eng_postCode', ""),
                                 (None, 'rightBelongs', owner_id),
                                 (None, 'ua_firstname', ""),
                                 (None, 'ukr_lastname', ""),
                                 (None, 'eng_firstname', ""),
                                 (None, 'ownershipType', ""),
                                 (None, 'ua_middlename', ""),
                                 (None, 'ua_streetType', ""),
                                 (None, 'ukr_firstname', ""),
                                 (None, 'eng_middlename', ""),
                                 (None, 'otherOwnership', ""),
                                 (None, 'ukr_middlename', ""),
                                 (None, 'rights_cityPath', ""),
                                 (None, 'ua_company_name', ""),
                                 (None, 'eng_company_name', ""),
                                 (None, 'ukr_company_name', ""),
                                 (None, 'percent-ownership', '100'),
                                 (None, 'ua_street_extendedstatus', ""),
                                 (None, 'ua_houseNum_extendedstatus', ""),
                                 (None, 'ua_postCode_extendedstatus', ""),
                                 (None, 'eng_postCode_extendedstatus', ""),
                                 (None, 'ua_middlename_extendedstatus', ""),
                                 (None, 'eng_middlename_extendedstatus', ""),
                                 (None, 'ukr_middlename_extendedstatus', ""),
                                 (None, 'ua_housePartNum_extendedstatus', ""),
                                 (None, 'ua_apartmentsNum_extendedstatus', "")   
                                ],
                                paper
                        )
                        record_counter += 1                          

        return {
            "step_12": extract
        }

    def _convert_step13(self):
        extract = {}
        record_counter = 1
        liabilities_desc_dict = {
            '54': 'Добровільне страхування',
            '55': 'Недержавне пенсійне забезпечення',
            '56': 'Утримання зазначеного у розділах ІІІ–V майна',
            '57': 'Погашення основної суми позики (кредиту)',
            '58': 'Погашення суми процентів за позикою (кредитом)',
            '59': 'Інші не зазначені у розділах ІІІ–V витрати',
            '60': 'Добровільне страхування',
            '61': 'Недержавне пенсійне забезпечення',
            '62': 'Утримання зазначеного у розділах ІІІ–V майна',
            '63': 'Погашення основної суми позики (кредиту)',
            '64': 'Погашення суми процентів за позикою (кредитом)'
        }
        liabilities_info = self._jsrch("liabilities")

        if liabilities_info:
            for liability_id, liability_dict in liabilities_info.items():
                owner_id = ('1'
                            if int(liability_id) in range(54,60)
                            else 'family')
                if liability_dict and \
                    (liability_dict.get('sum') or liability_dict.get('sum_foreign')):
                    extract[record_counter] = self._convert_using_rules(
                        [
                          (None, 'person', owner_id),
                          (None, 'currency', ""),
                          (None, 'guarantor', ""),
                          (None, 'iteration', ""),
                          (None, 'dateOrigin', ""),
                          (None, 'objectType', ""),
                          (None, 'margin-emitent', ""),
                          ('sum', 'sizeObligation', ''),
                          (None, 'emitent_citizen', ""),
                          (None, 'otherObjectType', ""),
                          (None, 'guarantor_exist_', ""),
                          ('sum_foreign', 'sizeAssets_abroad_declcomua', ''),
                          (None, 'guarantor_realty', ""),
                          (None, 'ownerThirdPerson', ""),
                          (None, 'emitent_ua_lastname', ""),
                          (None, 'emitent_eng_fullname', ""),
                          (None, 'emitent_ua_firstname', ""),
                          (None, 'emitent_ukr_fullname', ""),
                          (None, 'emitent_ua_middlename', ""),
                          (None, 'ownerThirdPersonThing', ""),
                          (None, 'emitent_ua_company_name', ""),
                          (None, 'guarantor_realty_exist_', ""),
                          (None, 'emitent_eng_company_name', ""),
                          ('sum_comment', 'emitent_ukr_company_name', ""),
                          ('sum_foreign_comment', 'emitent_ua_sameRegLivingAddress', ""),
                          (None, 'emitent_eng_company_code_extendedstatus', "")
                        ],
                        liability_dict
                    )
                    extract[record_counter]['objectType'] = \
                        liabilities_desc_dict[liability_id]
                    
                    record_counter += 1

        return {
            "step_13": extract
        }

    def _convert_step11(self):
        extract = {}
        record_counter = 1
        income_desc_dict = {'5': 'Загальна сума сукупного доходу',
                           '6': 'Заробітна плата, інші виплати та винагороди, нараховані (виплачені) декларанту відповідно до умов трудового або цивільно-правового договору',
                           '7': 'Дохід від викладацької, наукової і творчої діяльності, медичної практики, інструкторіської та суддівської практики із спорту',
                           '8': 'Авторська винагорода, інші доходи від реалізації майнових прав інтелектуальної власності',
                           '9': 'Дивіденди, проценти',
                           '10': 'Матеріальна допомога',
                           '11': 'Дарунки, призи, виграші',
                           '12': 'Допомога по безробіттю',
                           '13': 'Аліменти',
                           '14': 'Cпадщина',
                           '15': 'Cтрахові виплати, страхові відшкодування',
                           '16': 'Дохід від відчуження рухомого та нерухомого майна',
                           '17': 'Дохід від провадження підприємницької та незалежної професійної діяльності',
                           '18': 'Дохід від відчуження цінних паперів та корпоративних прав',
                           '19': 'Дохід від передачі в оренду майна',
                           '20': 'Iнші види доходів',
                           '22': 'Одержані з джерел за межами України членами сім’ї декларанта',
                           '21': 'Одержані з джерел за межами України декларантом'
        }
        incomes_info = self._jsrch('income')

        if incomes_info:
            for income_key, income_dict in incomes_info.items():
                if not income_dict:
                    continue

                if income_key in ('21', '22'):
                    for income_item in income_dict:
                        if income_item['uah_equal'] != '':
                            owner_id = ('1'
                                        if income_key == '21'
                                        else 'family')
                            extract[record_counter] = \
                                self._convert_using_rules(
                                [
                                  (None, 'person', owner_id),
                                  (None, 'rights', {}),
                                  (None, 'iteration', ""),
                                  (None, 'objectType', ""),
                                  ('uah_equal', 'sizeIncome', ""),
                                  (None, 'inner_or_outer_declcomua', "outer"),
                                  (None, 'source_citizen', 'Юридична особа, зареєстрована за кордоном'),
                                  (None, 'otherObjectType', ""),
                                  (None, 'source_ua_lastname', ""),
                                  (None, 'source_eng_fullname', ""),
                                  (None, 'source_ua_firstname', ""),
                                  (None, 'source_ukr_fullname', ""),
                                  (None, 'source_ua_middlename', ""),
                                  ('source_name', 'source_ua_company_name', ""),
                                  (None, 'source_eng_company_name', ""),
                                  ('country', 'income_country_name_declcomua', ""),
                                  (None, 'source_ukr_company_name', ""),
                                  (None, 'source_ua_sameRegLivingAddress', "")
                                ],
                                income_item
                            )
                            extract[record_counter]['objectType'] = \
                                income_desc_dict[income_key]
                            extract[record_counter]['rights'][owner_id] = \
                                self._convert_using_rules(
                                    [
                                     (None, 'citizen', ""),
                                     (None, 'ua_city', ""),
                                     (None, 'ua_street', ""),
                                     (None, 'ua_lastname', ""),
                                     (None, 'ua_postCode', ""),
                                     (None, 'eng_lastname', ""),
                                     (None, 'eng_postCode', ""),
                                     (None, 'rightBelongs', owner_id),
                                     (None, 'ua_firstname', ""),
                                     (None, 'ukr_lastname', ""),
                                     (None, 'eng_firstname', ""),
                                     (None, 'ownershipType', ""),
                                     (None, 'ua_middlename', ""),
                                     (None, 'ua_streetType', ""),
                                     (None, 'ukr_firstname', ""),
                                     (None, 'eng_middlename', ""),
                                     (None, 'otherOwnership', ""),
                                     (None, 'ukr_middlename', ""),
                                     (None, 'rights_cityPath', ""),
                                     (None, 'ua_company_name', ""),
                                     (None, 'eng_company_name', ""),
                                     (None, 'ukr_company_name', ""),
                                     (None, 'percent-ownership', '100'),
                                     (None, 'ua_street_extendedstatus', ""),
                                     (None, 'ua_houseNum_extendedstatus', ""),
                                     (None, 'ua_postCode_extendedstatus', ""),
                                     (None, 'eng_postCode_extendedstatus', ""),
                                     (None, 'ua_middlename_extendedstatus', ""),
                                     (None, 'eng_middlename_extendedstatus', ""),
                                     (None, 'ukr_middlename_extendedstatus', ""),
                                     (None, 'ua_housePartNum_extendedstatus', ""),
                                     (None, 'ua_apartmentsNum_extendedstatus', "")
                                    ],
                                    income_item
                            )
                            record_counter += 1
                else:
                    if income_dict.get('family') or income_dict.get('value'):
                        for sum_type in ('value', 'family'):
                            if not income_dict.get(sum_type):
                                continue

                            owner_id = ('1'
                                        if sum_type == 'value'
                                        else 'family')
                            extract[record_counter] = \
                                self._convert_using_rules(
                                [
                                  (None, 'person', owner_id),
                                  (None, 'rights', {}),
                                  (None, 'iteration', ""),
                                  (None, 'objectType', ""),
                                  (None, 'sizeIncome', income_dict[sum_type]),
                                  (None, 'inner_or_outer_declcomua', 'inner'),
                                  (None, 'source_citizen', 'Юридична особа, зареєстрована в Україні'),
                                  (None, 'otherObjectType', ""),
                                  (None, 'source_ua_lastname', ""),
                                  (None, 'source_eng_fullname', ""),
                                  (None, 'source_ua_firstname', ""),
                                  (None, 'source_ukr_fullname', ""),
                                  (None, 'source_ua_middlename', ""),
                                  ('source_name', 'source_ua_company_name', ""),
                                  (None, 'source_eng_company_name', ""),
                                  ('country', 'income_country_name_declcomua', ""),
                                  (None, 'source_ukr_company_name', ""),
                                  (None, 'source_ua_sameRegLivingAddress', "")
                                ],
                                income_dict
                            )                     
                            extract[record_counter]['objectType'] = \
                                income_desc_dict[income_key]
                            extract[record_counter]['rights'][owner_id] = \
                                self._convert_using_rules(
                                    [
                                     (None, 'citizen', ""),
                                     (None, 'ua_city', ""),
                                     (None, 'ua_street', ""),
                                     (None, 'ua_lastname', ""),
                                     (None, 'ua_postCode', ""),
                                     (None, 'eng_lastname', ""),
                                     (None, 'eng_postCode', ""),
                                     (None, 'rightBelongs', owner_id),
                                     (None, 'ua_firstname', ""),
                                     (None, 'ukr_lastname', ""),
                                     (None, 'eng_firstname', ""),
                                     (None, 'ownershipType', ""),
                                     (None, 'ua_middlename', ""),
                                     (None, 'ua_streetType', ""),
                                     (None, 'ukr_firstname', ""),
                                     (None, 'eng_middlename', ""),
                                     (None, 'otherOwnership', ""),
                                     (None, 'ukr_middlename', ""),
                                     (None, 'rights_cityPath', ""),
                                     (None, 'ua_company_name', ""),
                                     (None, 'eng_company_name', ""),
                                     (None, 'ukr_company_name', ""),
                                     (None, 'percent-ownership', '100'),
                                     (None, 'ua_street_extendedstatus', ""),
                                     (None, 'ua_houseNum_extendedstatus', ""),
                                     (None, 'ua_postCode_extendedstatus', ""),
                                     (None, 'eng_postCode_extendedstatus', ""),
                                     (None, 'ua_middlename_extendedstatus', ""),
                                     (None, 'eng_middlename_extendedstatus', ""),
                                     (None, 'ukr_middlename_extendedstatus', ""),
                                     (None, 'ua_housePartNum_extendedstatus', ""),
                                     (None, 'ua_apartmentsNum_extendedstatus', "")
                                    ],
                                    income_dict
                            )
                            record_counter += 1

        return {
            "step_11": extract
        }

    def convert(self):
        new_doc = self._meta_information()

        # Basic information
        new_doc["data"].update(self._convert_step0())

        # Information on the declarant
        new_doc["data"].update(self._convert_step1())

        # Information about delcarant's family
        new_doc["data"].update(self._convert_step2())

        # Information about declarant's real estate
        new_doc["data"].update(self._convert_step3())

        # step_6
        new_doc["data"].update(self._convert_step6())

        # step_7
        new_doc["data"].update(self._convert_step7())

        # step_8
        new_doc["data"].update(self._convert_step8())

        # step_12
        new_doc["data"].update(self._convert_step12())

        #step_13
        new_doc["data"].update(self._convert_step13())

        #step_11
        new_doc["data"].update(self._convert_step11()) 
        # Filling in the empty spaces
        new_doc["data"].update({
            "step_4": {},   # Об'єкти незавершеного будівництва
            "step_5": {},   # Бенефіціарна власність
            "step_9": {},   # Ціне рухоме майно
            "step_10": {},  # Нематеріальні активи
            "step_14": {},  # Видатки та правочини
            "step_15": {},  # Робота за сумісництвом
            "step_16": {},  # Членство декларанта в організаціях та їх органах
        })

        return new_doc


if __name__ == '__main__':
    if len(sys.argv) < 3:
        logger.error(
            "You should provide two params: input and output directories")
        exit()

    in_dir = sys.argv[1]
    out_dir = sys.argv[2]
    if (not os.path.isdir(in_dir) and \
        not os.path.isdir(out_dir)):
        logger.error(
            "Input and Output directories should exist. Check it.")
        exit()        

    for i, file_name in enumerate(glob.iglob(in_dir + '/*/' + "*.json")):
        basename = os.path.basename(file_name)
        subdir = os.path.dirname(file_name).split("/")[-1]

        new_file = os.path.join(out_dir, subdir, basename)
        with open(file_name, 'r') as infile:
            try:
                old_json = json.load(infile)
            except json.decoder.JSONDecodeError:
                logger.error('Empty or broken file: {}'.format(file_name))
                continue
            try:
                conv = Converter(old_json)

                os.makedirs(os.path.dirname(new_file), exist_ok=True)
                with open(new_file, "w") as fp:
                    json.dump(conv.convert(), fp, indent=4, ensure_ascii=False)

            # TODO: also intercept FS errors?
            except ConverterError as e:
                logger.error('Cannot convert file {}: {}'.format(
                    file_name, str(e)))
                continue
            except OSError as e:
                logging.error('OS error on {}: {}'.format(file_name, str(e)))
                continue