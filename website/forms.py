import re

from django import forms


class SubscriptionForm(forms.Form):
    email = forms.EmailField(max_length=254, widget=forms.EmailInput(attrs={
        "id": "email", "placeholder": "you@example.com", "autocomplete": "email",
        "aria-describedby": "email-errors",
    }))

    def clean_email(self):
        return self.cleaned_data["email"].strip().lower()


class CheckoutForm(forms.Form):
    def __init__(self, *args, cart=None, **kwargs):
        super().__init__(*args, **kwargs)
        prompts = [f"{line['quantity']} × {line['name']}: {line['order_note_prompt']}"
                   for line in (cart or {}).get("lines", []) if line.get("order_note_prompt")]
        if prompts:
            self.fields["notes"].required = True
            self.fields["notes"].label = "Your combo choices"
            self.fields["notes"].help_text = " ".join(prompts) + " For allergies, please call the shop before ordering."
            self.fields["notes"].error_messages["required"] = "Tell us your choices for each combo in your order."
            self.fields["notes"].widget.attrs["placeholder"] = "List your choices for each combo."

    checkout_token = forms.UUIDField(widget=forms.HiddenInput)
    customer_name = forms.CharField(label="Your name", max_length=80,
        widget=forms.TextInput(attrs={"autocomplete": "name", "placeholder": "Name for collection"}))
    phone = forms.CharField(label="Phone number", max_length=25,
        help_text="The shop can call you about your order.",
        widget=forms.TextInput(attrs={"type": "tel", "autocomplete": "tel", "placeholder": "e.g. 024 123 4567"}))
    notes = forms.CharField(label="Anything we should know?", max_length=500, required=False,
        help_text="Optional. For allergies, please call the shop before ordering.",
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "Milk preference, no sugar…"}))

    def clean_customer_name(self):
        value = " ".join(self.cleaned_data["customer_name"].split())
        if len(value) < 2:
            raise forms.ValidationError("Enter a name with at least two characters.")
        return value

    def clean_phone(self):
        value = re.sub(r"[\s()\-]", "", self.cleaned_data["phone"])
        if re.fullmatch(r"0\d{9}", value):
            return "+233" + value[1:]
        if re.fullmatch(r"\+[1-9]\d{7,14}", value):
            return value
        raise forms.ValidationError("Enter a Ghanaian number starting with 0, or include your country code (e.g. +233).")
