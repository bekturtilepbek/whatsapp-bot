"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import {
  addProductPhotos,
  createProduct,
  deleteProductPhoto,
  productPhotoUrl,
  updateProduct,
  type Product,
  type ProductInput,
  type ProductPhoto,
} from "@/lib/api";
import { useToast } from "@/components/ToastProvider";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { NumberField } from "@/components/ui/NumberField";
import { Switch } from "@/components/ui/Switch";
import { Textarea } from "@/components/ui/Textarea";

interface ProductFormProps {
  botId: string;
  apiBaseUrl: string;
  /** Если задан — режим редактирования, иначе — создание нового товара. */
  product?: Product;
}

interface FormState {
  name: string;
  price: string;
  sku: string;
  description: string;
  displayOverride: boolean;
  showName: boolean;
  showDescription: boolean;
  showPrice: boolean;
}

function initialState(product: Product | undefined): FormState {
  const hasOverride = !!product && Object.keys(product.display_custom).length > 0;
  return {
    name: product?.name ?? "",
    price: product?.price ?? "",
    sku: product?.sku ?? "",
    description: product?.description ?? "",
    displayOverride: hasOverride,
    showName: product?.display_custom.show_name ?? true,
    showDescription: product?.display_custom.show_description ?? true,
    showPrice: product?.display_custom.show_price ?? true,
  };
}

function toInput(state: FormState): ProductInput {
  return {
    name: state.name.trim(),
    price: state.price.trim() === "" ? null : Number(state.price),
    sku: state.sku.trim() === "" ? null : state.sku.trim(),
    description: state.description.trim() === "" ? null : state.description.trim(),
    display_custom: state.displayOverride
      ? {
          show_name: state.showName,
          show_description: state.showDescription,
          show_price: state.showPrice,
        }
      : {},
  };
}

export function ProductForm({ botId, apiBaseUrl, product }: ProductFormProps) {
  const router = useRouter();
  const { showError, showSuccess } = useToast();
  const [state, setState] = useState<FormState>(() => initialState(product));
  const [newPhotos, setNewPhotos] = useState<File[]>([]);
  const [photos, setPhotos] = useState<ProductPhoto[]>(product?.photos ?? []);
  const [saving, setSaving] = useState(false);
  const [photoBusy, setPhotoBusy] = useState(false);

  // PATCH на бэкенде мержит поля: null/пропуск значит «не трогать», а не
  // «очистить» (см. аналогичное поведение bots.image_prompt/pdf_prompt).
  // Значит стереть цену/артикул/описание обратно в пустоту через эту форму
  // нельзя — предупреждаем об этом в режиме редактирования там, где у товара
  // уже есть значение поля. Берём исходное значение из product, а не из
  // текущего state — подсказка не должна пропадать в момент, когда админ
  // как раз стирает поле (самый нужный момент её увидеть).
  const clearHint = "Поле нельзя очистить обратно — здесь можно только заменить значение на другое.";
  const showPriceHint = !!product && !!product.price && product.price.trim() !== "";
  const showSkuHint = !!product && !!product.sku && product.sku.trim() !== "";
  const showDescriptionHint = !!product && !!product.description && product.description.trim() !== "";

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (state.name.trim() === "") {
      showError("Название обязательно");
      return;
    }
    if (!product && newPhotos.length === 0) {
      showError("Нужно хотя бы одно фото");
      return;
    }
    setSaving(true);
    try {
      const input = toInput(state);
      if (product) {
        await updateProduct(apiBaseUrl, botId, product.id, input);
      } else {
        await createProduct(apiBaseUrl, botId, input, newPhotos);
      }
      showSuccess("Товар сохранён");
      router.push(`/bots/${botId}/products`);
      router.refresh();
    } catch (err) {
      showError(err instanceof Error ? err.message : "Не удалось сохранить");
    } finally {
      setSaving(false);
    }
  };

  const handleAddPhotos = async (files: FileList | null) => {
    if (!product || !files || files.length === 0) {
      return;
    }
    setPhotoBusy(true);
    try {
      const added = await addProductPhotos(apiBaseUrl, botId, product.id, Array.from(files));
      setPhotos((current) => [...current, ...added]);
      showSuccess("Фото добавлено");
    } catch (err) {
      showError(err instanceof Error ? err.message : "Не удалось добавить фото");
    } finally {
      setPhotoBusy(false);
    }
  };

  const handleDeletePhoto = async (photoId: string) => {
    if (!product) {
      return;
    }
    setPhotoBusy(true);
    try {
      await deleteProductPhoto(apiBaseUrl, botId, product.id, photoId);
      setPhotos((current) => current.filter((p) => p.id !== photoId));
      showSuccess("Фото удалено");
    } catch (err) {
      showError(err instanceof Error ? err.message : "Не удалось удалить фото");
    } finally {
      setPhotoBusy(false);
    }
  };

  return (
    // noValidate — та же причина, что и в BotSettingsForm: нативная
    // HTML5-валидация (required/min) тихо блокирует submit ДО нашей проверки.
    <form noValidate onSubmit={(e) => void handleSubmit(e)} className="max-w-xl space-y-5">
      <Card className="flex flex-col gap-4 p-5">
        <label className="mb-0 block text-sm font-medium text-ink">
          Название
          <Input
            type="text"
            value={state.name}
            onChange={(e) => setState({ ...state, name: e.target.value })}
            className="mt-1.5"
          />
        </label>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="mb-0 block text-sm font-medium text-ink">
              Цена
              <NumberField
                min={0}
                step={0.01}
                value={state.price}
                onChange={(e) => setState({ ...state, price: e.target.value })}
                className="mt-1.5"
              />
            </label>
            {showPriceHint && <p className="mt-1.5 text-xs text-ink-soft">{clearHint}</p>}
          </div>
          <div>
            <label className="mb-0 block text-sm font-medium text-ink">
              Артикул (SKU)
              <Input
                type="text"
                value={state.sku}
                onChange={(e) => setState({ ...state, sku: e.target.value })}
                className="mt-1.5"
              />
            </label>
            {showSkuHint && <p className="mt-1.5 text-xs text-ink-soft">{clearHint}</p>}
          </div>
        </div>
        <div>
          <label className="mb-0 block text-sm font-medium text-ink">
            Описание
            <Textarea
              rows={4}
              value={state.description}
              onChange={(e) => setState({ ...state, description: e.target.value })}
              className="mt-1.5"
            />
          </label>
          {showDescriptionHint && <p className="mt-1.5 text-xs text-ink-soft">{clearHint}</p>}
        </div>
      </Card>

      <Card className="p-5">
        <label className="mb-0 flex items-center gap-2.5 text-sm font-medium text-ink">
          <Switch
            checked={state.displayOverride}
            onChange={(e) => setState({ ...state, displayOverride: e.target.checked })}
          />
          Переопределить вывод для этого товара
        </label>
        {state.displayOverride && (
          <fieldset className="mt-4 flex flex-col gap-3 border-0 p-0">
            <label className="mb-0 flex items-center gap-2.5 text-sm font-medium text-ink">
              <Switch
                checked={state.showName}
                onChange={(e) => setState({ ...state, showName: e.target.checked })}
              />
              Показывать название
            </label>
            <label className="mb-0 flex items-center gap-2.5 text-sm font-medium text-ink">
              <Switch
                checked={state.showDescription}
                onChange={(e) => setState({ ...state, showDescription: e.target.checked })}
              />
              Показывать описание
            </label>
            <label className="mb-0 flex items-center gap-2.5 text-sm font-medium text-ink">
              <Switch
                checked={state.showPrice}
                onChange={(e) => setState({ ...state, showPrice: e.target.checked })}
              />
              Показывать цену
            </label>
          </fieldset>
        )}
      </Card>

      {!product && (
        <Card className="p-5">
          <label className="mb-0 block text-sm font-medium text-ink">
            Фото
            <input
              type="file"
              multiple
              accept="image/jpeg,image/png,image/webp"
              onChange={(e) => setNewPhotos(e.target.files ? Array.from(e.target.files) : [])}
              className="mt-1.5 block text-sm text-ink-soft file:mr-3 file:rounded-lg file:border file:border-border file:bg-surface file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-ink hover:file:border-ink-faint"
            />
          </label>
        </Card>
      )}

      {product && (
        <Card className="p-5">
          <h2 className="mb-4 text-[15px] font-semibold text-ink">Фото</h2>
          <div className="flex flex-wrap gap-4">
            {photos.map((photo) => (
              <div key={photo.id} className="w-24">
                <img
                  src={productPhotoUrl(apiBaseUrl, botId, product.id, photo.id)}
                  alt="Фото товара"
                  className="h-24 w-24 rounded-lg object-cover"
                />
                <Button
                  type="button"
                  variant="danger"
                  className="mt-2 w-full justify-center"
                  disabled={photoBusy || photos.length <= 1}
                  title={photos.length <= 1 ? "Нельзя удалить единственное фото" : undefined}
                  onClick={() => void handleDeletePhoto(photo.id)}
                >
                  Удалить фото
                </Button>
              </div>
            ))}
          </div>
          <label className="mb-0 mt-4 block text-sm font-medium text-ink">
            Добавить ещё
            <input
              type="file"
              multiple
              accept="image/jpeg,image/png,image/webp"
              disabled={photoBusy}
              onChange={(e) => void handleAddPhotos(e.target.files)}
              className="mt-1.5 block text-sm text-ink-soft file:mr-3 file:rounded-lg file:border file:border-border file:bg-surface file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-ink hover:file:border-ink-faint disabled:opacity-60"
            />
          </label>
        </Card>
      )}

      <Button type="submit" disabled={saving}>
        {saving ? "Сохраняем…" : "Сохранить"}
      </Button>
    </form>
  );
}
