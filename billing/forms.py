from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.utils.text import slugify

from .models import Shop


class ShopSignupForm(UserCreationForm):
    """
    Self-serve signup: creates a brand-new Shop plus its first (owner) user
    account in one step. Everything the shop needs — menu, ingredients,
    orders — starts completely empty; there's no shared data with any
    other shop on the platform.
    """
    shop_name = forms.CharField(
        max_length=100, label="Shop / stall name",
        widget=forms.TextInput(attrs={'placeholder': "e.g. Sunset Snacks"}),
    )
    email = forms.EmailField(required=False)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'email')

    def clean_shop_name(self):
        name = self.cleaned_data['shop_name'].strip()
        if not name:
            raise forms.ValidationError("Shop name can't be blank.")
        base_slug = slugify(name) or 'shop'
        slug = base_slug
        suffix = 1
        while Shop.objects.filter(slug=slug).exists():
            suffix += 1
            slug = f"{base_slug}-{suffix}"
        self.cleaned_data['shop_slug'] = slug
        return name

    def save(self, commit=True):
        user = super().save(commit=False)
        if self.cleaned_data.get('email'):
            user.email = self.cleaned_data['email']
        if commit:
            user.save()
            shop = Shop.objects.create(
                name=self.cleaned_data['shop_name'],
                slug=self.cleaned_data['shop_slug'],
                contact_email=self.cleaned_data.get('email', ''),
            )
            from .models import Membership
            Membership.objects.create(user=user, shop=shop, role=Membership.Role.OWNER)
        return user
