from django.contrib import admin

# Register your models here.
from .models import Article, ArticleCategory, Carousel, Device, FeederModel, ControlBoardModel, FirmwareUpdate


class ArticleCategoryAdmin(admin.ModelAdmin):
    list_display = ["name"]
    list_filter = ["name"]


class ArticleAdmin(admin.ModelAdmin):
    list_display = ("id", "category", "author", "title", "published_at", "created_at", "modified_at")
    list_filter = ("id", "title", "author", "published_at")


class CarouselAdmin(admin.ModelAdmin):
    list_display = ("name", "slide_label", "start_datetime")
    list_filter = ("name", "slide_label", "start_datetime")


class FeederModelAdmin(admin.ModelAdmin):
    list_display = ("id", "brand_name", "model_name")
    list_filter = ("brand_name", "model_name")


class DeviceAdmin(admin.ModelAdmin):
    list_display = ("id", "control_board_identifier", "secret_key", "activation_qrcode")
    list_filter = ["id", "control_board_identifier"]


class ControlBoardModelAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "revision", "description")


class FirmwareUpdateAdmin(admin.ModelAdmin):
    list_display = ("id", "version", "control_board", "created_at")


admin.site.register(ArticleCategory, ArticleCategoryAdmin)
admin.site.register(Article, ArticleAdmin)
admin.site.register(Carousel, CarouselAdmin)
admin.site.register(FeederModel, FeederModelAdmin)
admin.site.register(Device, DeviceAdmin)
admin.site.register(ControlBoardModel, ControlBoardModelAdmin)
admin.site.register(FirmwareUpdate, FirmwareUpdateAdmin)
