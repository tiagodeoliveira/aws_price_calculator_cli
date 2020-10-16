from __future__ import print_function, unicode_literals
import inquirer
from yaspin import yaspin

import pprint
import requests 
import botocore.session
import pandas as pd

session = botocore.session.get_session()
regions = session.get_available_regions('ec2')
pp = pprint.PrettyPrinter(indent=4)

PRICING_API='https://pricing.us-east-1.amazonaws.com'
OFFER_INDEX='/offers/v1.0/aws/index.json'
DONE_ITEM = '✓ done'
SPINNER_OK = '✅ '
SPINNER_FAIL = '💥 '

def load_offers():
    with yaspin(text='Querying ' + PRICING_API + OFFER_INDEX, color="yellow") as spinner:
        try:
            index_response = requests.get(PRICING_API + OFFER_INDEX)
            return index_response.json()['offers']
            spinner.ok(SPINNER_OK)
        except:
            spinner.fail(SPINNER_FAIL)
            return None

def prompt_region():
    question = [
        inquirer.List('region',
                  message="Select and AWS Region?",
                  choices=regions,
                  default='eu-central-1',
                  carousel=True,
              )
    ]

    answer = inquirer.prompt(question)
    return answer['region'] if answer else None

def prompt_service(services_list, service):
    question = [
        inquirer.List('service',
                  message="Select and AWS Service?",
                  choices=services_list,
                  default=service,
                  carousel=True,
              )
    ]

    answer = inquirer.prompt(question)
    return answer['service'] if answer else None

def get_regional_service(region, offer):
    regional_service_offer = requests.get(PRICING_API + offer['currentRegionIndexUrl'])
    offer_regions = regional_service_offer.json()['regions']
    offer_region = offer_regions.get(region, {})
    current_version_url = offer_region.get('currentVersionUrl', None)

    if current_version_url:
        with yaspin(text='Querying ' + PRICING_API + current_version_url, color="yellow") as spinner:
            service_pricing = requests.get(PRICING_API + current_version_url)
            spinner.ok(SPINNER_OK)
            return service_pricing.json()

def get_options_list(options_list, service_offer):
    return_options = []

    for product in options_list:
        for offer in options_list[product]:
            for price in options_list[product][offer]['priceDimensions']:
                item = options_list.get(product, {}).get(offer, {}).get('priceDimensions', {}).get(price, {})
                if item:
                    item_id = item['rateCode'].split('.')

                    product_offer = service_offer['products'][item_id[0]]

                    return_options.append({
                        'name': item['description'],
                        'key': item['rateCode'],
                        'unit': item['unit'],
                        'price': item['pricePerUnit']['USD'],
                        'productFamily': product_offer.get('productFamily', 'Other'),
                        'attributes': product_offer.get('attributes', {}),
                    })

    return return_options

def get_product_label(x):
    if x['attributes'] and x['attributes']['servicecode'] == 'AmazonEC2':
        return f"{x['attributes']['instanceFamily']} - {x['attributes']['instanceType']} - {x['attributes']['operatingSystem']} - vcpu={x['attributes']['vcpu']} - {x['attributes']['tenancy']} - {x['attributes']['preInstalledSw']} - {x['attributes']['capacitystatus']}"
    else:
        return x['name']

def prompt_service_form(service_offer, service):
    terms = service_offer.get('terms', {})
    products = service_offer.get('products', {})

    ondemand_options = get_options_list(terms.get('OnDemand', {}), service_offer)
    reserved_options = get_options_list(terms.get('Reserved', {}), service_offer)

    style_options = [
        'OnDemand' if len(ondemand_options) > 1 else None,
        'Reserved'  if len(reserved_options) > 1 else None,
        DONE_ITEM,
    ]

    styles = [
        inquirer.List('style',
            message='Select the pricing model',
            choices=[s for s in style_options if s is not None],
            carousel=True,
        )
    ]

    calculations = []
    while True:
        selected_style = inquirer.prompt(styles)

        if selected_style and selected_style['style'] == 'OnDemand':
            choices = ondemand_options
        elif selected_style and selected_style['style'] == 'Reserved':
            choices = reserved_options
        else:
            return calculations

        prod_families = sorted(set([x.get('productFamily') for x in choices if x.get('productFamily') is not None]))
        prod_families.append(('<- back', '<- back'))

        family_options = [
            inquirer.List('family',
                message='Select the product family',
                choices=prod_families,
                carousel=True,
            ),
        ]

        choosen_family = inquirer.prompt(family_options)
        if choosen_family and choosen_family['family'] != '<- back':
            type_choices = list(filter(lambda x: x.get('productFamily') == choosen_family['family'], choices))
            selected_type_choices = sorted([(get_product_label(x), x['key']) for x in type_choices])
            selected_type_choices.append(('<- back', '<- back'))

            pricing_options = [
                inquirer.List('type',
                    message='Select the product',
                    choices=selected_type_choices,
                    carousel=True,
                ),
            ]

            choosen_pricing = inquirer.prompt(pricing_options)

            if choosen_pricing and choosen_pricing['type'] != '<- back':
                choosen_items = list(filter(lambda x: x['key'] == choosen_pricing['type'], choices))
                choosen_item = choosen_items[0] if choosen_items else None
                if choosen_item:
                    questions = [
                        inquirer.Text('value', message=f'{choosen_item["productFamily"]} - How many {choosen_item["unit"]}?'),
                    ]

                    answers = inquirer.prompt(questions)
                    if answers and answers['value']:
                        calculations.append({
                            'name': choosen_pricing['type'], 
                            'service': service,
                            'type': selected_style['style'],
                            'family': choosen_family['family'],
                            'value': float(answers['value']) * float(choosen_item['price']),
                        })

def print_summary(total_expenses):
    flatten_items = [item for items in total_expenses for item in items]
    if flatten_items:
        df = pd.DataFrame(data=flatten_items)
        print(df.groupby(["service", "type"]).sum())
        print("---------------------------------------")
        print("Grand Total: USD", format(df["value"].sum(), 'f'))

def execute_routine(offers):
    services = sorted([x for x in offers])
    service = None
    region = prompt_region()
    if region:
        services.append(DONE_ITEM)
        total_expenses = []
        while True:
            service = prompt_service(services, service)
            if (service and service != DONE_ITEM):
                offer = offers[service]
                service_offer = get_regional_service(region, offer)
                if (service_offer):
                    total_expenses.append(prompt_service_form(service_offer, service))
            else: 
                break

        print_summary(total_expenses)

offers = load_offers()
if offers:
    execute_routine(offers)
else:
    print("Could not fetch offers!")